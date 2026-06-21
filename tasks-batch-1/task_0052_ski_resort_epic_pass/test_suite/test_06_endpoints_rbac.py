"""Cross-cutting surface: authentication/authorization, not-found, pagination and
filtered lists, FK reverse-reachability reads, the duplicate-tier and
required-field validations, and the resort/interchange administrative
transitions.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    factories,
    fixtures,
    NON_EXISTENT_UUID,
)

ADMIN = TEST_USERS["network_admin_headers"]
OPS = TEST_USERS["resort_ops_headers"]
REFUND = TEST_USERS["refund_admin_headers"]


# ─── Auth / RBAC ─────────────────────────────────────────────────────────────

def test_missing_auth_headers_returns_auth_missing(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` does not name a
    role the system recognizes, the request is rejected with `ERR_AUTH_MISSING`."

    Design: Corner/errors/missing_auth_headers_returns_auth_missing
    """
    resp = api.raw_get("/resorts", {"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value, 401)


def test_resort_ops_cannot_create_resort(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/resort_ops_cannot_create_resort
    """
    resp = api.create_resort(
        factories.create_resort_payload(name="Sneaky Resort", home_network="EPIC"), OPS
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)


def test_refund_admin_cannot_issue_pass(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/refund_admin_cannot_issue_pass
    """
    product = fixtures.create_product(api, tier="EPIC_DAY", price_cents=5000)
    resp = api.create_pass(
        factories.create_pass_payload(product["id"], holder_name="Wrong Role"), REFUND
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)


def test_resort_ops_cannot_approve_refund(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/resort_ops_cannot_approve_refund
    """
    product = fixtures.create_product(api, tier="FULL_EPIC", price_cents=6000)
    issued = fixtures.issue_pass(api, product["id"], holder_name="RBAC Host")
    fixtures.activate_pass(api, issued["id"])
    rr = validate_success(
        api.create_refund_request(
            factories.create_refund_request_payload(issued["id"], "INJURY"), OPS
        ),
        201,
    )
    pass_ver = fixtures.get_pass(api, issued["id"])["version"]
    resp = api.approve_refund_request(
        rr["id"], factories.approve_refund_payload(pass_ver), OPS
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)


def test_refund_admin_can_open_refund_request_shared_op(api):
    """PRD §2.1: "The opening of a refund request is shared: a `ResortOps` or a
    `RefundAdmin` may both create one."

    Design: Corner/rbac/refund_admin_can_open_refund_request_shared_op
    """
    product = fixtures.create_product(api, tier="FULL_EPIC", price_cents=6000)
    issued = fixtures.issue_pass(api, product["id"], holder_name="Shared Host")
    fixtures.activate_pass(api, issued["id"])
    rr = validate_success(
        api.create_refund_request(
            factories.create_refund_request_payload(issued["id"], "RELOCATION"), REFUND
        ),
        201,
    )
    assert rr["status"] == "PENDING", "RefundAdmin may open a refund request (shared op)"


# ─── Not-found / validation ──────────────────────────────────────────────────

def test_get_unknown_pass_returns_not_found(api):
    """PRD §2.5: "the server validates those references left-to-right and rejects
    the first one that does not resolve with `ERR_NOT_FOUND`."

    Design: Corner/endpoints/get_unknown_pass_returns_not_found
    """
    resp = api.get_pass(NON_EXISTENT_UUID, OPS)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_scan_unknown_resort_returns_not_found(api):
    """PRD §2.5: "the server validates those references left-to-right and rejects
    the first one that does not resolve with `ERR_NOT_FOUND`."

    Design: Corner/endpoints/scan_unknown_resort_returns_not_found
    """
    product = fixtures.create_product(api, tier="FULL_EPIC", price_cents=8000)
    issued = fixtures.issue_pass(api, product["id"], holder_name="NF Holder")
    token = issued["magnetic_token"]
    fixtures.activate_pass(api, issued["id"])
    resp = api.scan_pass(issued["id"], factories.scan_payload(NON_EXISTENT_UUID, token), OPS)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_create_pass_missing_holder_name_returns_validation(api):
    """PRD §2.5: "all required body fields must be present and well-typed — for
    instance... the `pass_product_id` and `holder_name` of a pass... A request with
    a missing or wrongly typed required field is rejected with `ERR_VALIDATION`."

    Design: Corner/validations/create_pass_missing_holder_name_returns_validation
    """
    product = fixtures.create_product(api, tier="FULL_EPIC", price_cents=8000)
    resp = api.create_pass({"pass_product_id": product["id"]}, OPS)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, 422)


def test_duplicate_pass_product_tier_returns_duplicate_tier(api):
    """PRD §3.1: "it must be unique across all pass products — an attempt to create
    a second product with a tier that already exists is rejected with
    `ERR_DUPLICATE_TIER`."

    Design: Corner/validations/duplicate_pass_product_tier_returns_duplicate_tier
    """
    fixtures.create_product(api, tier="LOCAL", price_cents=5000)
    resp = api.create_pass_product(
        factories.create_pass_product_payload(tier="LOCAL", price_cents=6000), ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_TIER.value, 409)


# ─── Defaults / administrative transitions ──────────────────────────────────

def test_resort_create_defaults_open_epic_gate_one(api):
    """PRD §3.1: "The `home_network`... is one of `EPIC` or `IKON`, defaulting to
    `EPIC` when omitted. The `gate_count`... must be at least 1 and defaults to 1
    when omitted. A freshly created resort begins in `status` `OPEN`."

    Design: Corner/entities/resort_create_defaults_open_and_gate_count_one
    """
    resort = validate_success(api.create_resort({"name": "Default Resort"}, ADMIN), 201)
    assert resort["status"] == "OPEN"
    assert resort["home_network"] == "EPIC"
    assert resort["gate_count"] == 1


def test_resort_suspend_sets_status_suspended(api):
    """PRD §3.1: "A resort may later be suspended, transitioning its `status` from
    `OPEN` to `SUSPENDED`".

    Design: Corner/endpoints/resort_suspend_sets_status_suspended
    """
    resort = fixtures.create_resort(api, name="ToSuspend", home_network="EPIC")
    suspended = validate_success(api.suspend_resort(resort["id"], ADMIN), 200)
    assert suspended["status"] == "SUSPENDED"


def test_interchange_agreement_terminate_sets_status_terminated(api):
    """PRD §3.1: "A new agreement begins in `status` `ACTIVE` and may later be
    terminated, moving its `status` from `ACTIVE` to `TERMINATED`".

    Design: Corner/endpoints/interchange_agreement_terminate_sets_status_terminated
    """
    resort = fixtures.create_resort(api, name="Term IKON", home_network="IKON")
    agr = fixtures.create_interchange_agreement(api, resort["id"], max_interchange_days=2)
    terminated = validate_success(api.terminate_interchange_agreement(agr["id"], ADMIN), 200)
    assert terminated["status"] == "TERMINATED"


# ─── Pagination / filtered lists ─────────────────────────────────────────────

def test_list_passes_pagination_envelope(api):
    """PRD §2.3: "The `limit` parameter caps how many items a single response
    returns... List responses surface their pagination state inside the `meta`
    object using exactly these fields: `limit`, `offset`, `total_count`, and
    `has_more`."

    Design: Corner/endpoints/list_passes_pagination_envelope
    """
    product = fixtures.create_product(api, tier="FULL_EPIC", price_cents=8000)
    fixtures.issue_pass(api, product["id"], holder_name="Pg A")
    fixtures.issue_pass(api, product["id"], holder_name="Pg B")
    resp = api.list_passes(OPS, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 1, "limit=1 returns a single item"
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


def test_list_passes_filter_by_pass_product_id(api):
    """PRD §4 (endpoint table): "GET `/passes` List passes (optional
    `pass_product_id` filter)".

    Design: Corner/endpoints/list_passes_filter_by_pass_product_id
    """
    prod_a = fixtures.create_product(api, tier="FULL_EPIC", price_cents=8000)
    prod_b = fixtures.create_product(api, tier="LOCAL", price_cents=5000)
    pass_a = fixtures.issue_pass(api, prod_a["id"], holder_name="A Holder")
    fixtures.issue_pass(api, prod_b["id"], holder_name="B Holder")
    resp = api.list_passes(OPS, params={"pass_product_id": prod_a["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert data[0]["id"] == pass_a["id"]


def test_fk_reverse_pass_lift_scans(api):
    """PRD §4 (endpoint table): "GET `/passes/{id}/lift-scans` List lift scans for a
    pass (optional `resort_id` filter)".

    Design: Corner/endpoints/fk_reverse_pass_lift_scans
    """
    _product, resort, fresh, _token = fixtures.setup_pass_with_granted_scans(
        api, scan_count=1, price_cents=8000, base_iso="2026-03-05T08:00:00Z",
        holder_name="FK Holder",
    )
    resp = api.list_pass_lift_scans(fresh["id"], OPS)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert data[0]["result"] == "GRANTED"


def test_fk_reverse_resort_lift_scans(api):
    """PRD §4 (endpoint table): "GET `/resorts/{id}/lift-scans` List lift scans
    performed at a resort".

    Design: Corner/endpoints/fk_reverse_resort_lift_scans
    """
    _product, resort, _fresh, _token = fixtures.setup_pass_with_granted_scans(
        api, scan_count=1, price_cents=8000, base_iso="2026-03-06T08:00:00Z",
        holder_name="SFK Holder",
    )
    resp = api.list_resort_lift_scans(resort["id"], OPS)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1


def test_fk_reverse_pass_buddy_tickets(api):
    """PRD §4 (endpoint table): "GET `/passes/{id}/buddy-tickets` List buddy tickets
    for a host pass".

    Design: Corner/endpoints/fk_reverse_pass_buddy_tickets
    """
    _product, resort, active, buddies = fixtures.setup_active_pass_with_buddies(
        api, num_buddies=1, allotment=2, buddy_price_cents=1000,
        clock_iso="2026-02-12T08:00:00Z", base_date="2026-02-12",
    )
    resp = api.list_pass_buddy_tickets(active["id"], OPS)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert data[0]["id"] == buddies[0]["id"]


def test_fk_reverse_resort_buddy_tickets(api):
    """PRD §4 (endpoint table): "GET `/resorts/{id}/buddy-tickets` List buddy
    tickets valid at a resort (optional `valid_date` filter)".

    Design: Corner/endpoints/fk_reverse_resort_buddy_tickets
    """
    _product, resort, _active, buddies = fixtures.setup_active_pass_with_buddies(
        api, num_buddies=1, allotment=2, buddy_price_cents=1000,
        clock_iso="2026-02-11T08:00:00Z", base_date="2026-02-11",
    )
    resp = api.list_resort_buddy_tickets(resort["id"], OPS)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert data[0]["id"] == buddies[0]["id"]


def test_fk_reverse_pass_refund_requests(api):
    """PRD §4 (endpoint table): "GET `/passes/{id}/refund-requests` List refund
    requests for a pass".

    Design: Corner/endpoints/fk_reverse_pass_refund_requests
    """
    product = fixtures.create_product(api, tier="FULL_EPIC", price_cents=6000)
    issued = fixtures.issue_pass(api, product["id"], holder_name="RR Host")
    fixtures.activate_pass(api, issued["id"])
    rr = fixtures.open_refund(api, issued["id"], reason="INJURY")
    resp = api.list_pass_refund_requests(issued["id"], REFUND)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert data[0]["id"] == rr["id"]


def test_fk_reverse_resort_interchange_agreements(api):
    """PRD §4 (endpoint table): "GET `/resorts/{id}/interchange-agreements` List
    interchange agreements for a resort".

    Design: Corner/endpoints/fk_reverse_resort_interchange_agreements
    """
    resort = fixtures.create_resort(api, name="IKON FK", home_network="IKON")
    agr = fixtures.create_interchange_agreement(api, resort["id"], max_interchange_days=3)
    resp = api.list_resort_interchange_agreements(resort["id"], OPS)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert data[0]["id"] == agr["id"]
