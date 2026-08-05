"""Producer registration, verification, and dual-axis product review."""
from test_helpers import (
    ApiErrorId, NON_EXISTENT_UUID,
    validate_success, validate_error, validate_paginated,
    make_producer_headers, TEST_USERS,
    create_producer_payload, create_product_payload,
    register_producer, create_registered_producer, create_policy, declare_product,
)

INSPECTOR = TEST_USERS["inspector_headers"]
ADMIN = TEST_USERS["admin_headers"]
PRODUCER = TEST_USERS["producer_headers"]


def test_register_producer_starts_pending_with_zero_ledger(api):
    """PRD §3.1: "On creation the producer starts in `PENDING_VERIFICATION` status,
    a one-time `verification_token` is minted, `verified_at` is left null, and
    `ytd_gross_sales_cents` is initialized to zero."

    Design: Corner/entities/producer_register_success_201
    """
    resp = api.create_producer(create_producer_payload(business_name="New Co"), PRODUCER)
    data = validate_success(resp, 201)
    assert data["status"] == "PENDING_VERIFICATION"
    assert data["ytd_gross_sales_cents"] == 0
    assert isinstance(data.get("verification_token"), str) and data["verification_token"]
    assert data.get("verified_at") in (None, "")


def test_get_unknown_producer_returns_not_found(api):
    """PRD §2.10: "The system then resolves every resource id named in the path or
    body, validated left-to-right, returning on the first missing reference with the
    matching not-found error (`ERR_PRODUCER_NOT_FOUND`, ... each HTTP 404)."

    Design: Corner/entities/producer_get_nonexistent_returns_not_found
    """
    resp = api.get_producer(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_PRODUCER_NOT_FOUND.value, 404)


def test_declare_product_missing_unit_price_rejected(api):
    """PRD §2.10: "any malformed body — a missing required field, a wrong type, an
    illegal enum value, a non-positive `gross_amount_cents`, or a bad
    `verification_token` — rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/product_create_missing_required_returns_invalid_request
    """
    producer = register_producer(api, business_name="Prod Co")
    pid = producer["id"]
    payload = create_product_payload(pid)
    del payload["unit_price_cents"]
    resp = api.create_product(payload, make_producer_headers(pid))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_verify_already_registered_producer_rejected(api):
    """PRD §3.1: "they present the `verification_token` in the request body, and if it
    equals the token the server minted at registration, the producer transitions from
    `PENDING_VERIFICATION` to `REGISTERED` and `verified_at` is stamped from the current
    logical clock. A token that does not match is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/state_machines/verify_already_registered_returns_invalid_request
    """
    producer = register_producer(api, business_name="Twice Co")
    pid, tok = producer["id"], producer["verification_token"]
    ph = make_producer_headers(pid)
    validate_success(api.verify_producer(pid, {"verification_token": tok}, ph), 200)
    resp = api.verify_producer(pid, {"verification_token": tok}, ph)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    after = validate_success(api.get_producer(pid, ph), 200)
    assert after["status"] == "REGISTERED"


def test_product_food_approve_independent_of_label_reject(api):
    """PRD §3.2: "A declared product begins with `compliance_status` of `DECLARED` and
    `label_status` of `LABEL_DRAFT`. These two axes evolve completely independently of
    one another."
    PRD §3.2: "An approval moves `compliance_status` from `DECLARED` to `APPROVED`, but
    only when all of the following hold: the policy for the product's category has
    `is_cottage_allowed` true; the product's `requires_refrigeration` is false;"

    Design: Difficulty/non_linear_state_machine/product_parallel_axes_independent
    """
    create_policy(api, food_category="BAKED_GOODS")
    producer = create_registered_producer(api, business_name="Cookie Corner")
    pid = producer["id"]
    product = declare_product(api, pid, name="Cookie", unit_price_cents=300)
    prid = product["id"]
    validate_success(api.review_food(prid, {"decision": "APPROVE"}, INSPECTOR), 200)
    validate_success(api.review_label(prid, {"decision": "REJECT", "reject_reason": "missing allergen line"}, INSPECTOR), 200)
    final = validate_success(api.get_product(prid, INSPECTOR), 200)
    assert final["compliance_status"] == "APPROVED"


def test_product_label_reject_independent_of_food_approve(api):
    """PRD §3.2: "A rejecting decision moves `label_status` to `LABEL_REJECTED` and
    records the supplied `reject_reason`."
    PRD §3.2: "These two axes evolve completely independently of one another."

    Design: Difficulty/non_linear_state_machine/product_parallel_axes_independent
    """
    create_policy(api, food_category="BAKED_GOODS")
    producer = create_registered_producer(api, business_name="Cookie Corner 2")
    pid = producer["id"]
    product = declare_product(api, pid, name="Cookie", unit_price_cents=300)
    prid = product["id"]
    validate_success(api.review_food(prid, {"decision": "APPROVE"}, INSPECTOR), 200)
    validate_success(api.review_label(prid, {"decision": "REJECT", "reject_reason": "missing allergen line"}, INSPECTOR), 200)
    final = validate_success(api.get_product(prid, INSPECTOR), 200)
    assert final["label_status"] == "LABEL_REJECTED"


def test_review_food_refrigerated_product_rejected(api):
    """PRD §3.2: "A category that is not cottage-allowed, a product that needs
    refrigeration, or a measured pH or water activity that exceeds a set ceiling all
    cause the approval to fail with `ERR_FOOD_NOT_COTTAGE_ALLOWED`."

    Design: Corner/validations/review_food_refrigerated_returns_not_cottage_allowed
    """
    create_policy(api, food_category="DAIRY", is_cottage_allowed=False,
                  class_b_required=True, requires_allergen_label=True)
    producer = create_registered_producer(api, business_name="Cold Co")
    pid = producer["id"]
    product = declare_product(api, pid, name="Cheesecake", food_category="DAIRY",
                              requires_refrigeration=True, unit_price_cents=1200)
    resp = api.review_food(product["id"], {"decision": "APPROVE"}, INSPECTOR)
    validate_error(resp, ApiErrorId.ERR_FOOD_NOT_COTTAGE_ALLOWED.value, 422)
    after = validate_success(api.get_product(product["id"], INSPECTOR), 200)
    assert after["compliance_status"] == "DECLARED"


def test_list_producers_pagination_envelope(api):
    """PRD §2.3: "Each list response carries `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object."

    Design: Corner/entities/producers_list_pagination_envelope
    """
    register_producer(api, business_name="L1", contact_email="l1@x.com")
    register_producer(api, business_name="L2", county="Marin",
                      water_source="PRIVATE_WELL", contact_email="l2@x.com")
    resp = api.list_producers(ADMIN, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] >= 2
    assert meta["has_more"] is True
