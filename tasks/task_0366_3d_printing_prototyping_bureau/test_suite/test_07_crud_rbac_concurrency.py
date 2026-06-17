"""CRUD basics, reference integrity, RBAC, OCC, and endpoint reads.

Covers:
  Corner/entities/create_bureau_returns_201_with_defaults
  Corner/entities/customer_missing_required_email_returns_invalid_request
  Corner/entities/order_line_quantity_zero_returns_invalid_request
  Corner/entities/get_customer_nonexistent_returns_not_found
  Corner/entities/create_order_line_unknown_print_file_returns_reference_not_found
  Corner/rbac/operator_cannot_create_order_returns_forbidden
  Corner/rbac/customer_cannot_check_printability_returns_forbidden
  Corner/rbac/missing_auth_headers_returns_unauthenticated
  Corner/cross_cutting_complexity_layers/occ_confirm_stale_order_version_returns_412
  Corner/cross_cutting_complexity_layers/occ_adjudicate_stale_run_version_returns_412
  Corner/endpoints/deposit_increments_wallet_and_lifetime
  Corner/endpoints/list_orders_pagination_envelope
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data, api_client,
    setup_catalogue, setup_run_failed, setup_order_with_line,
    upload_file, quote_order, add_line, adjudicate_run,
    create_bureau_payload, create_customer_payload, create_order_payload,
    create_order_line_payload, create_material_payload, FILE_B, TEST_USERS,
    NON_EXISTENT_UUID, make_customer_headers,
)

ADMIN = TEST_USERS["bureau_admin_headers"]
OPERATOR = TEST_USERS["operator_headers"]
QA = TEST_USERS["qa_reviewer_headers"]


# ─── entities ─────────────────────────────────────────

def test_create_bureau_defaults_and_version(api):
    """PRD §3.1: "A `BureauAdmin` bootstraps a tenant by creating a `Bureau` with a
    `name` and optionally a `cooldown_buffer_min` (the required gap between
    post-process station jobs, defaulting to 15 minutes) and a
    `shift_capacity_minutes` (per-machine schedulable minutes per shift, defaulting
    to 480). A new bureau starts at `version` 1 with its `clock_utc` set to the
    epoch instant."

    Design: Corner/entities/create_bureau_returns_201_with_defaults
    """
    res = api.create_bureau({"name": "B Defaults"}, ADMIN)
    bureau = validate_success(res, 201)
    assert bureau["cooldown_buffer_min"] == 15
    assert bureau["shift_capacity_minutes"] == 480
    assert bureau["version"] == 1


def test_customer_missing_email_returns_invalid_request(api):
    """PRD §3.1: "Customers are registered by a `BureauAdmin` against a bureau by
    supplying `bureau_id`, a bureau-unique `email`, and a `display_name`".
    PRD §2.11: "(5) request well-formedness — required body fields present and
    well-typed ... else `ERR_INVALID_REQUEST`".

    Design: Corner/entities/customer_missing_required_email_returns_invalid_request
    """
    bureau = get_success_data(api.create_bureau(create_bureau_payload(name="B E"), ADMIN))
    res = api.create_customer({"bureau_id": bureau["id"], "display_name": "NoEmail"}, ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_order_line_quantity_zero_returns_invalid_request(api):
    """PRD §3.3: "a `quantity` of identical parts (which must be at least 1)".
    PRD §2.11: "(5) request well-formedness — ... `quantity` at least 1 ... else
    `ERR_INVALID_REQUEST`".

    Design: Corner/entities/order_line_quantity_zero_returns_invalid_request
    """
    env = setup_catalogue(with_spool=False, with_machine=False)
    f = upload_file(env["bureau"]["id"], env["customer"]["id"], geometry=FILE_B)
    order = get_success_data(api.create_order(
        create_order_payload(env["bureau"]["id"], env["customer"]["id"]),
        env["cust_headers"]))
    res = api.create_order_line(
        create_order_line_payload(order["id"], f["id"], env["material"]["id"],
                                  layer_height_mm=0.10, quantity=0),
        env["cust_headers"])
    validate_error(res, "ERR_INVALID_REQUEST")


def test_get_nonexistent_customer_returns_not_found(api):
    """PRD §2.5: "the system validates the path resources left to right and rejects
    the first identifier that does not resolve within the bureau scope with
    `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_customer_nonexistent_returns_not_found
    """
    get_success_data(api.create_bureau(create_bureau_payload(name="B NF"), ADMIN))
    res = api.get_customer(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, "ERR_NOT_FOUND")


def test_order_line_unknown_print_file_returns_reference_not_found(api):
    """PRD §2.5: "Foreign-key references carried in a request body — `customer_id`,
    `material_id`, `print_file_id`, `machine_id`, `spool_id`, `order_id`, and
    `order_line_id` — must resolve to an existing resource within the same bureau;
    a dangling body reference is rejected with `ERR_REFERENCE_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/create_order_line_unknown_print_file_returns_reference_not_found
    """
    env = setup_catalogue(with_spool=False, with_machine=False)
    order = get_success_data(api.create_order(
        create_order_payload(env["bureau"]["id"], env["customer"]["id"]),
        env["cust_headers"]))
    res = api.create_order_line(
        create_order_line_payload(order["id"], NON_EXISTENT_UUID, env["material"]["id"],
                                  layer_height_mm=0.10, quantity=1),
        env["cust_headers"])
    validate_error(res, "ERR_REFERENCE_NOT_FOUND")


# ─── rbac ─────────────────────────────────────────────

def test_operator_cannot_create_order_forbidden(api):
    """PRD §2.1: "When the headers are present but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: order creation is authorized for `Customer` only.

    Design: Corner/rbac/operator_cannot_create_order_returns_forbidden
    """
    env = setup_catalogue(with_spool=False, with_machine=False)
    res = api.create_order(
        create_order_payload(env["bureau"]["id"], env["customer"]["id"]),
        OPERATOR)
    validate_error(res, "ERR_FORBIDDEN")


def test_customer_cannot_check_printability_forbidden(api):
    """PRD §2.1: "When the headers are present but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: the printability check is authorized for `QAReviewer` only.

    Design: Corner/rbac/customer_cannot_check_printability_returns_forbidden
    """
    env = setup_catalogue(with_spool=False)
    f = upload_file(env["bureau"]["id"], env["customer"]["id"], geometry=FILE_B)
    res = api.check_print_file(f["id"], {"material_id": env["material"]["id"]},
                               env["cust_headers"])
    validate_error(res, "ERR_FORBIDDEN")


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    bureau = get_success_data(api.create_bureau(create_bureau_payload(name="B AUTH"), ADMIN))
    res = api.get_bureau(bureau["id"], headers={})
    validate_error(res, "ERR_UNAUTHENTICATED")


# ─── OCC (optimistic concurrency) ─────────────────────

def test_confirm_with_stale_order_version_returns_412(api):
    """PRD §2.10: "a request to confirm an order must carry `expected_order_version`
    matching that order's current `version`. If another writer has advanced the
    order's version since the client last read it — for instance because a reprint
    failure or a re-quote has already mutated the order's totals and bumped its
    version — the client's observed `grand_total_cents` is out of date, and
    confirming would escrow against a stale figure; the confirm is therefore
    rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_confirm_stale_order_version_returns_412
    """
    env = setup_order_with_line(geometry=FILE_B, layer_height_mm=0.10, quantity=1,
                                check_file=True)
    quoted = quote_order(env)
    stale_version = quoted["version"]
    # Add a second line and re-quote, advancing the order's version.
    add_line(env, env["file"]["id"], layer_height_mm=0.10, quantity=1)
    quote_order(env)
    res = api.confirm_order(env["order"]["id"], {"expected_order_version": stale_version},
                            env["cust_headers"])
    validate_error(res, "ERR_STALE_VERSION")


def test_adjudicate_with_stale_run_version_returns_412(api):
    """PRD §2.10: "the adjudicate request must carry `expected_run_version` matching
    the target run's current `version`; if the run's version has advanced since the
    client last observed it — for instance because the run was already adjudicated
    once, advancing its version and re-attributing cost — a second adjudication
    carrying the stale version would double-reconcile and is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_adjudicate_stale_run_version_returns_412
    """
    env = setup_run_failed("FILE_DEFECT", geometry=FILE_B, layer_height_mm=0.10,
                           quantity=1, duration_min=24, spool_grams=1000)
    stale_version = env["run"]["version"]
    # First adjudicate succeeds (advances run.version).
    adjudicate_run(env, start_min=30, duration_min=24)
    # Second adjudicate carrying the pre-adjudication (stale) version.
    res = api.adjudicate_print_run(env["run"]["id"], {
        "expected_run_version": stale_version,
        "machine_id": env["machine"]["id"], "spool_id": env["spool"]["id"],
        "start_min": 60, "duration_min": 24}, QA)
    validate_error(res, "ERR_STALE_VERSION")


# ─── endpoints ────────────────────────────────────────

def test_deposit_increments_wallet_and_lifetime(api):
    """PRD §3.1: "Funds enter a customer's wallet through an administrator deposit
    that supplies `amount_cents`, raising both `wallet_balance_cents` and
    `lifetime_deposits_cents` by that amount."

    Design: Corner/endpoints/deposit_increments_wallet_and_lifetime
    """
    bureau = get_success_data(api.create_bureau(create_bureau_payload(name="B DEP"), ADMIN))
    cust = get_success_data(api.create_customer(
        create_customer_payload(bureau["id"], email="dep@x.com", display_name="DEP"), ADMIN))
    res = api.deposit(cust["id"], {"amount_cents": 30000}, ADMIN)
    updated = validate_success(res, 200)
    assert updated["wallet_balance_cents"] == 30000
    assert updated["lifetime_deposits_cents"] == 30000


def test_list_orders_pagination_envelope(api):
    """PRD §2.3: "Every list-based response includes the following fields inside the
    `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/endpoints/list_orders_pagination_envelope
    """
    bureau = get_success_data(api.create_bureau(create_bureau_payload(name="B LIST"), ADMIN))
    cust = get_success_data(api.create_customer(
        create_customer_payload(bureau["id"], email="list@x.com", display_name="LIST"), ADMIN))
    ch = make_customer_headers(cust["id"])
    api.create_order(create_order_payload(bureau["id"], cust["id"]), ch)
    api.create_order(create_order_payload(bureau["id"], cust["id"]), ch)
    res = api.list_orders(ADMIN, params={"customer_id": cust["id"]})
    body = res.json()
    assert body["response_type"] == "array"
    assert isinstance(body["meta"].get("api_request_id"), str)
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 2, meta["total_count"]
    assert meta["has_more"] is False
