"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures produce
clear "Setup failed" errors rather than confusing assertion failures.

Identity threading: every Customer-role call in a fixture uses
make_customer_headers(customer["id"]) so ownership checks pass; opaque roles use
the shared TEST_USERS constants.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_customer_payload, create_address_payload, create_credit_adjustment_payload,
    create_template_payload, create_project_payload, create_photo_payload,
    create_promotion_payload, create_promo_window_payload, create_surge_window_payload,
    create_order_payload, create_shipment_payload, create_cancel_payload, create_clock_payload,
)
from .test_users import TEST_USERS, make_customer_headers

ADMIN = TEST_USERS["catalog_admin_headers"]
OPERATOR = TEST_USERS["production_operator_headers"]


# ─── Primitive builders ───────────────────────────────────────────────

def set_clock(to_iso8601: str):
    """Move the logical clock (CatalogAdmin)."""
    return get_success_data(api_client.set_clock(create_clock_payload(to_iso8601), ADMIN))


def create_customer(email="c@x.com", full_name="C"):
    return get_success_data(
        api_client.create_customer(create_customer_payload(email=email, full_name=full_name), ADMIN)
    )


def seed_credit(customer_id, amount_cents, reason="seed"):
    return get_success_data(
        api_client.adjust_credit(customer_id, create_credit_adjustment_payload(amount_cents, reason), ADMIN)
    )


def create_address(customer_id, headers=None, **overrides):
    h = headers or make_customer_headers(customer_id)
    return get_success_data(api_client.create_address(customer_id, create_address_payload(**overrides), h))


def create_template(**overrides):
    return get_success_data(api_client.create_template(create_template_payload(**overrides), ADMIN))


def create_project(customer, template, title="P", headers=None):
    h = headers or make_customer_headers(customer["id"])
    return get_success_data(
        api_client.create_project(
            create_project_payload(customer_id=customer["id"], template_id=template["id"], title=title), h
        )
    )


def upload_photo(project, headers, **overrides):
    return get_success_data(api_client.upload_photo(project["id"], create_photo_payload(**overrides), headers))


def upload_n_photos(project, headers, n=2, dpi=300):
    for i in range(n):
        upload_photo(project, headers, filename=f"p{i}.jpg", dpi=dpi)


def autolayout(project, headers):
    return get_success_data(api_client.autolayout(project["id"], headers))


def generate_proof(project, headers):
    """Read current project version, then generate a proof with that version."""
    pv = get_success_data(api_client.get_project(project["id"], headers))["version"]
    return get_success_data(api_client.generate_proof(project["id"], {"expected_project_version": pv}, headers))


def approve_proof(proof, headers):
    return get_success_data(api_client.approve_proof(proof["id"], headers))


def create_promotion(code, kind, value=0, **overrides):
    return get_success_data(api_client.create_promotion(create_promotion_payload(code, kind, value, **overrides), ADMIN))


def create_promo_window(promotion_id, starts_at, ends_at):
    return get_success_data(
        api_client.create_promo_window(promotion_id, create_promo_window_payload(starts_at, ends_at), ADMIN)
    )


def create_surge_window(**overrides):
    return get_success_data(api_client.create_surge_window(create_surge_window_payload(**overrides), ADMIN))


# ─── Tier 1/2: Project lifecycle composites ───────────────────────────

def setup_laid_out_project(template_overrides=None, email="c@x.com", n_photos=2, dpi=300):
    """Customer + template + project + N photos + autolayout → LAID_OUT.

    Returns dict: cust, headers, tmpl, proj (LAID_OUT).
    """
    cust = create_customer(email=email)
    h = make_customer_headers(cust["id"])
    tmpl = create_template(**(template_overrides or {}))
    proj = create_project(cust, tmpl, headers=h)
    upload_n_photos(proj, h, n=n_photos, dpi=dpi)
    autolayout(proj, h)
    proj = get_success_data(api_client.get_project(proj["id"], h))
    return {"cust": cust, "headers": h, "tmpl": tmpl, "proj": proj}


def setup_project_in_proof(template_overrides=None, email="c@x.com", n_photos=2):
    """LAID_OUT project + one GENERATED proof → project IN_PROOF.

    Returns dict: cust, headers, tmpl, proj (IN_PROOF), proof (GENERATED).
    """
    ctx = setup_laid_out_project(template_overrides=template_overrides, email=email, n_photos=n_photos)
    proof = generate_proof(ctx["proj"], ctx["headers"])
    ctx["proof"] = proof
    ctx["proj"] = get_success_data(api_client.get_project(ctx["proj"]["id"], ctx["headers"]))
    return ctx


def setup_approved_project(template_overrides=None, email="c@x.com", n_photos=2, with_address=True, seed_credit_cents=0):
    """Full design lifecycle → project APPROVED (proof approved, photos LOCKED).

    Returns dict: cust, headers, tmpl, proj (APPROVED), proof (APPROVED),
    and addr when with_address.
    """
    ctx = setup_project_in_proof(template_overrides=template_overrides, email=email, n_photos=n_photos)
    if seed_credit_cents:
        seed_credit(ctx["cust"]["id"], seed_credit_cents)
    approve_proof(ctx["proof"], ctx["headers"])
    ctx["proj"] = get_success_data(api_client.get_project(ctx["proj"]["id"], ctx["headers"]))
    if with_address:
        ctx["addr"] = create_address(ctx["cust"]["id"], headers=ctx["headers"])
    return ctx


# ─── Tier 3: Order lifecycle composites ───────────────────────────────

def place_order(ctx, **order_overrides):
    """Place an order on ctx's approved project + address. Returns Order."""
    payload = create_order_payload(
        project_id=ctx["proj"]["id"], ship_address_id=ctx["addr"]["id"], **order_overrides
    )
    return get_success_data(api_client.create_order(payload, ctx["headers"]))


def pay_order(order, headers):
    return get_success_data(api_client.pay_order(order["id"], headers))


def setup_paid_order(template_overrides=None, order_overrides=None, seed_credit_cents=0, email="c@x.com"):
    """Approved project + placed order + pay → PAID / IN_PRODUCTION with a QUEUED job.

    Returns dict extending setup_approved_project with: order (paid), and helper keys.
    """
    ctx = setup_approved_project(template_overrides=template_overrides, seed_credit_cents=seed_credit_cents, email=email)
    order = place_order(ctx, **(order_overrides or {}))
    ctx["order"] = pay_order(order, ctx["headers"])
    return ctx


def get_production_job(order):
    """Fetch the (first) production job for an order via the operator listing."""
    data = get_success_data(api_client.list_production_jobs(order["id"], OPERATOR))
    return data[0]


def advance_job_to_done(order):
    """Advance the order's production job QUEUED→PRINTING→FINISHING→DONE. Returns job."""
    job = get_production_job(order)
    for _ in range(3):
        job = get_success_data(api_client.advance_job(job["id"], OPERATOR))
    return job


def setup_order_with_done_job(template_overrides=None, order_overrides=None, email="c@x.com"):
    """Paid order whose ProductionJob has been advanced to DONE.

    Returns dict extending setup_paid_order with: job (DONE).
    """
    ctx = setup_paid_order(template_overrides=template_overrides, order_overrides=order_overrides, email=email)
    ctx["job"] = advance_job_to_done(ctx["order"])
    return ctx


def create_shipment(ctx):
    """Create a shipment for ctx['order'] (requires DONE job). Returns Shipment."""
    return get_success_data(
        api_client.create_shipment(ctx["order"]["id"], create_shipment_payload(ctx["addr"]["id"]), OPERATOR)
    )


def setup_order_with_label(template_overrides=None, order_overrides=None, email="c@x.com"):
    """Paid order, job DONE, one LABEL_CREATED shipment; order still IN_PRODUCTION.

    Returns dict extending setup_order_with_done_job with: shipment (LABEL_CREATED).
    """
    ctx = setup_order_with_done_job(template_overrides=template_overrides, order_overrides=order_overrides, email=email)
    ctx["shipment"] = create_shipment(ctx)
    return ctx


def advance_shipment(shipment):
    return get_success_data(api_client.advance_shipment(shipment["id"], OPERATOR))


def setup_order_delivered(template_overrides=None, order_overrides=None, email="c@x.com"):
    """Paid order driven fully through to fulfillment DELIVERED (shipment DELIVERED).

    Returns dict extending setup_order_with_label with: shipment (IN_TRANSIT after
    the first advance) — call advance_shipment again in the test to reach DELIVERED.
    """
    ctx = setup_order_with_label(template_overrides=template_overrides, order_overrides=order_overrides, email=email)
    ctx["shipment"] = advance_shipment(ctx["shipment"])  # LABEL_CREATED → IN_TRANSIT (order → SHIPPED)
    return ctx


def cancel_order(order, headers, refund_destination):
    return get_success_data(
        api_client.cancel_order(order["id"], create_cancel_payload(refund_destination), headers)
    )
