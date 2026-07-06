"""Payment settlement, optimistic concurrency on revision, and access control."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    assert_payment,
    create_customer_payload, create_diagnose_payload, create_revision_payload,
    create_truck_stock_payload,
    setup_declined_none_request, setup_diagnosed_request, setup_scheduled_request,
    create_technician, create_part, create_truck_stock, get_service_request,
    make_customer_headers, make_technician_headers, TEST_USERS,
)

ADMIN = TEST_USERS["service_admin_headers"]


# ─── Corner: payment_amount_mismatch_rejected ──────────────────────────────
def test_payment_not_matching_amount_due_rejected(api):
    """PRD §3.8: "The payment's `amount_cents` must equal the request's current
    `amount_due_cents`, otherwise the payment is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH`
    (HTTP 422)."

    Design: Corner/validations/payment_amount_mismatch_rejected
    """
    ctx = setup_declined_none_request(model="NA0")  # declined NONE request owes 8900
    res = api.create_payment(ctx["sr_id"], {"amount_cents": 5000, "method": "CARD"},
                             make_customer_headers(ctx["cust_id"]))
    validate_error(res, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH)


# ─── Corner: payment_exact_amount_recorded ─────────────────────────────────
def test_payment_of_exact_amount_due_recorded(api):
    """PRD §3.8: "A recorded payment is created in `status` `RECORDED`, which is terminal."
    PRD §3.4: "the request's `amount_due_cents` is set to its `diagnostic_fee_cents` — the
    diagnostic visit is owed even though the repair was refused."

    Design: Corner/validations/payment_exact_amount_recorded
    """
    ctx = setup_declined_none_request(model="NB0")
    sr = get_service_request(ctx)
    assert sr["amount_due_cents"] == 8900
    res = api.create_payment(ctx["sr_id"], {"amount_cents": 8900, "method": "CARD"},
                             make_customer_headers(ctx["cust_id"]))
    payment = validate_success(res, 201)
    assert_payment(payment)
    assert payment["status"] == "RECORDED"


# ─── Corner: occ_estimate_revision_stale_version_rejected ──────────────────
def test_second_revision_with_stale_version_rejected(api):
    """PRD §2.7: "If they differ — meaning the request's version has advanced since it was read,
    for example because a prior revision already superseded the pending estimate and bumped the
    version — the write is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the
    technician from acting on a stale view of the request."

    Design: Corner/cross_cutting/occ_estimate_revision_stale_version_rejected
    """
    ctx = setup_diagnosed_request(model="NF0")
    sr = get_service_request(ctx)
    stale_version = sr["version"]
    # First revision with the observed version succeeds and advances ServiceRequest.version.
    validate_success(api.revise_estimate(
        ctx["sr_id"],
        create_revision_payload([{"minutes": 60}], [{"part_id": ctx["part_id"], "quantity": 1}], stale_version),
        make_technician_headers(ctx["tech_id"])), 201)
    # Second revision still carrying the now-stale version is rejected.
    res = api.revise_estimate(
        ctx["sr_id"],
        create_revision_payload([{"minutes": 30}], [{"part_id": ctx["part_id"], "quantity": 1}], stale_version),
        make_technician_headers(ctx["tech_id"]))
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)


# ─── Corner: customer_cannot_diagnose_returns_unauthorized ─────────────────
def test_customer_cannot_diagnose(api):
    """PRD §2.1: "If the headers are well-formed but the declared role is not permitted to
    perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/customer_cannot_diagnose_returns_unauthorized
    """
    ctx = setup_scheduled_request(model="NE0")
    res = api.diagnose(ctx["sr_id"], create_diagnose_payload([{"minutes": 40}], []),
                       make_customer_headers(ctx["cust_id"]))
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)


# ─── Corner: missing_headers_returns_unauthenticated ───────────────────────
def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "If either header is missing or malformed, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_headers_returns_unauthenticated
    """
    res = api.create_customer(create_customer_payload(), {})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)


# ─── Corner: duplicate_truck_stock_line_rejected ───────────────────────────
def test_duplicate_truck_stock_line_rejected(api):
    """PRD §2.9: "At most one truck-stock line may exist for any given pair of `technician_id`
    and `part_id`."

    Design: Corner/validations/duplicate_truck_stock_line_rejected
    """
    tech = create_technician()
    part = create_part(part_number="PD")
    create_truck_stock(tech["id"], part["id"], quantity_on_hand=5)
    res = api.create_truck_stock(
        create_truck_stock_payload(tech["id"], part["id"], quantity_on_hand=2), ADMIN)
    validate_error(res, ApiErrorId.ERR_DUPLICATE_TRUCK_STOCK)
