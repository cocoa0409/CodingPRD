"""Composite setup helpers for multi-step test prerequisites.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints, because the server is restarted (empty database) before every test.

Identity threading: SalesRep and Customer are entity-backed roles. After a
fixture creates one, ownership-gated calls use the per-instance header builders
(make_sales_rep_headers / make_customer_headers) with the real entity id, never
the shared TEST_USERS fallback.

Fixtures use get_success_data() (lenient validator) internally so setup failures
surface as clear "Setup failed" errors rather than confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_customer_payload, create_sales_rep_payload, create_product_payload,
    create_job_payload, measure_payload, create_estimate_payload, issue_payload,
    create_install_crew_payload, create_install_slot_payload,
    create_warranty_claim_payload,
)
from .test_users import (
    TEST_USERS, ANONYMOUS_HEADERS,
    make_sales_rep_headers, make_customer_headers,
)

# Default deterministic clock used by every time-gated fixture.
DEFAULT_CLOCK = "2026-06-01T00:00:00.000Z"
FAR_FUTURE_VALID_UNTIL = "2026-07-01T00:00:00.000Z"


# ─── Clock control ────────────────────────────────────────────────────

def set_clock(to_iso8601: str):
    """Set the server UTC clock (Admin-only test-driving capability)."""
    return get_success_data(
        api_client.set_clock(to_iso8601, TEST_USERS["admin_headers"])
    )


# ─── Tier 0: Actors + catalog ─────────────────────────────────────────

def register_customer(**overrides):
    """Create a Customer. Returns the Customer dict (id == X-User-ID)."""
    return get_success_data(
        api_client.create_customer(create_customer_payload(**overrides), ANONYMOUS_HEADERS)
    )


def register_sales_rep(**overrides):
    """Create a SalesRep. Returns the SalesRep dict (id == X-User-ID)."""
    return get_success_data(
        api_client.create_sales_rep(create_sales_rep_payload(**overrides), ANONYMOUS_HEADERS)
    )


def create_product(**overrides):
    """Create an ACTIVE catalog Product (Admin)."""
    return get_success_data(
        api_client.create_product(create_product_payload(**overrides), TEST_USERS["admin_headers"])
    )


def create_crew(**overrides):
    """Create an AVAILABLE InstallCrew (Scheduler)."""
    return get_success_data(
        api_client.create_install_crew(
            create_install_crew_payload(**overrides), TEST_USERS["scheduler_headers"]
        )
    )


def setup_actors_and_product(clock=DEFAULT_CLOCK, product_overrides=None):
    """Register customer + rep, set the clock, create one product.

    Returns (customer, sales_rep, product). The base building block for almost
    every other fixture.
    """
    customer = register_customer()
    sales_rep = register_sales_rep()
    if clock is not None:
        set_clock(clock)
    product = create_product(**(product_overrides or {}))
    return customer, sales_rep, product


# ─── Tier 1: Job state progression ────────────────────────────────────

def create_draft_job(declared_sqft=200, clock=DEFAULT_CLOCK, product_overrides=None,
                     job_overrides=None):
    """Customer + rep + product + a DRAFT job.

    Returns (customer, sales_rep, product, job).
    """
    customer, sales_rep, product = setup_actors_and_product(
        clock=clock, product_overrides=product_overrides
    )
    rep_headers = make_sales_rep_headers(sales_rep["id"])
    job = get_success_data(api_client.create_job(
        create_job_payload(customer["id"], sales_rep["id"], product["id"],
                           declared_sqft=declared_sqft, **(job_overrides or {})),
        rep_headers,
    ))
    return customer, sales_rep, product, job


def create_measured_job(declared_sqft=200, measured_sqft=200, tear_out_sqft=0,
                        room_count=1, clock=DEFAULT_CLOCK, product_overrides=None):
    """Drive a job DRAFT -> MEASURED with the supplied geometry.

    Returns (customer, sales_rep, product, job) where job is the measured job dict.
    """
    customer, sales_rep, product, job = create_draft_job(
        declared_sqft=declared_sqft, clock=clock, product_overrides=product_overrides
    )
    job = get_success_data(api_client.measure_job(
        job["id"],
        measure_payload(measured_sqft=measured_sqft, tear_out_sqft=tear_out_sqft,
                        room_count=room_count),
        TEST_USERS["estimator_headers"],
    ))
    return customer, sales_rep, product, job


# ─── Tier 2: Estimates ────────────────────────────────────────────────

def create_measured_estimate(declared_sqft=200, measured_sqft=200, tear_out_sqft=0,
                             room_count=1, valid_until=FAR_FUTURE_VALID_UNTIL,
                             clock=DEFAULT_CLOCK, product_overrides=None):
    """Measured job + a DRAFT MEASURED estimate (not yet issued).

    Returns (customer, sales_rep, product, job, estimate).
    """
    customer, sales_rep, product, job = create_measured_job(
        declared_sqft=declared_sqft, measured_sqft=measured_sqft,
        tear_out_sqft=tear_out_sqft, room_count=room_count,
        clock=clock, product_overrides=product_overrides,
    )
    rep_headers = make_sales_rep_headers(sales_rep["id"])
    estimate = get_success_data(api_client.create_estimate(
        create_estimate_payload(job["id"], variant="MEASURED", valid_until=valid_until),
        rep_headers,
    ))
    return customer, sales_rep, product, job, estimate


def create_issued_estimate(declared_sqft=200, measured_sqft=200, tear_out_sqft=0,
                           room_count=1, valid_until=FAR_FUTURE_VALID_UNTIL,
                           clock=DEFAULT_CLOCK, product_overrides=None):
    """Job MEASURED -> ESTIMATED by issuing the MEASURED estimate (DRAFT -> ISSUED).

    Returns (customer, sales_rep, product, job, estimate) where job is now
    ESTIMATED and estimate is ISSUED. Re-fetches the job to expose its bumped
    version for downstream OCC-aware steps.
    """
    customer, sales_rep, product, job, estimate = create_measured_estimate(
        declared_sqft=declared_sqft, measured_sqft=measured_sqft,
        tear_out_sqft=tear_out_sqft, room_count=room_count,
        valid_until=valid_until, clock=clock, product_overrides=product_overrides,
    )
    rep_headers = make_sales_rep_headers(sales_rep["id"])
    estimate = get_success_data(api_client.issue_estimate(
        estimate["id"], issue_payload(job["version"]), rep_headers,
    ))
    job = get_success_data(api_client.get_job(job["id"], rep_headers))
    return customer, sales_rep, product, job, estimate


def create_accepted_job(declared_sqft=200, measured_sqft=200, tear_out_sqft=0,
                        room_count=1, valid_until=FAR_FUTURE_VALID_UNTIL,
                        clock=DEFAULT_CLOCK, product_overrides=None):
    """Customer accepts the ISSUED estimate: job ESTIMATED -> ACCEPTED, a
    MaterialOrder is spawned in ORDERED.

    Returns (customer, sales_rep, product, job, estimate, material_order).
    """
    customer, sales_rep, product, job, estimate = create_issued_estimate(
        declared_sqft=declared_sqft, measured_sqft=measured_sqft,
        tear_out_sqft=tear_out_sqft, room_count=room_count,
        valid_until=valid_until, clock=clock, product_overrides=product_overrides,
    )
    cust_headers = make_customer_headers(customer["id"])
    estimate = get_success_data(api_client.accept_estimate(estimate["id"], cust_headers))
    job = get_success_data(api_client.get_job(job["id"], cust_headers))
    material_order = get_material_order_for_job(job["id"])
    return customer, sales_rep, product, job, estimate, material_order


def get_material_order_for_job(job_id):
    """Return the (single) MaterialOrder spawned for a job, or None."""
    data, _meta = _list(api_client.list_job_material_orders(job_id, TEST_USERS["scheduler_headers"]))
    return data[0] if data else None


# ─── Tier 3: Material order + slot + install lifecycle ────────────────

def create_accepted_job_material_received(
        declared_sqft=200, measured_sqft=200, tear_out_sqft=0, room_count=1,
        clock=DEFAULT_CLOCK, product_overrides=None):
    """ACCEPTED job whose MaterialOrder has been received (RECEIVED).

    Product defaults to lead_time_days=0 so the order is immediately receivable
    at the default clock. Returns
    (customer, sales_rep, product, job, estimate, material_order).
    """
    overrides = {"lead_time_days": 0}
    overrides.update(product_overrides or {})
    customer, sales_rep, product, job, estimate, material_order = create_accepted_job(
        declared_sqft=declared_sqft, measured_sqft=measured_sqft,
        tear_out_sqft=tear_out_sqft, room_count=room_count,
        clock=clock, product_overrides=overrides,
    )
    material_order = get_success_data(
        api_client.receive_material_order(material_order["id"], TEST_USERS["scheduler_headers"])
    )
    return customer, sales_rep, product, job, estimate, material_order


def schedule_slot(job_id, crew_id, start_at, end_at):
    """Create one InstallSlot for an accepted job on a crew (Scheduler)."""
    return get_success_data(api_client.create_install_slot(
        create_install_slot_payload(job_id, crew_id, start_at=start_at, end_at=end_at),
        TEST_USERS["scheduler_headers"],
    ))


def create_scheduled_job(declared_sqft=200, measured_sqft=200, tear_out_sqft=0,
                         room_count=1, crew_overrides=None,
                         start_at="2026-06-02T09:00:00.000Z",
                         end_at="2026-06-02T15:00:00.000Z",
                         clock=DEFAULT_CLOCK, product_overrides=None,
                         receive_material=True):
    """ACCEPTED job with one SCHEDULED InstallSlot on a skill-matched crew.

    Crew skill_categories default to the product category so the slot create
    passes the skill check. Returns
    (customer, sales_rep, product, job, estimate, material_order, crew, slot).
    """
    if receive_material:
        customer, sales_rep, product, job, estimate, material_order = \
            create_accepted_job_material_received(
                declared_sqft=declared_sqft, measured_sqft=measured_sqft,
                tear_out_sqft=tear_out_sqft, room_count=room_count,
                clock=clock, product_overrides=product_overrides)
    else:
        overrides = {"lead_time_days": 0}
        overrides.update(product_overrides or {})
        customer, sales_rep, product, job, estimate, material_order = create_accepted_job(
            declared_sqft=declared_sqft, measured_sqft=measured_sqft,
            tear_out_sqft=tear_out_sqft, room_count=room_count,
            clock=clock, product_overrides=overrides)

    crew_kwargs = {"skill_categories": [product["category"]], "daily_sqft_capacity": 5000}
    crew_kwargs.update(crew_overrides or {})
    crew = create_crew(**crew_kwargs)
    slot = schedule_slot(job["id"], crew["id"], start_at, end_at)
    return customer, sales_rep, product, job, estimate, material_order, crew, slot


def create_completed_job(declared_sqft=200, measured_sqft=200, tear_out_sqft=0,
                         room_count=1, product_overrides=None,
                         clock=DEFAULT_CLOCK):
    """Drive a job all the way to COMPLETED (warranty_risk_score now set).

    Returns (customer, sales_rep, product, job, crew, slot) where job is the
    completed job dict (re-fetched, so warranty_risk_score is populated).
    """
    customer, sales_rep, product, job, estimate, material_order, crew, slot = \
        create_scheduled_job(
            declared_sqft=declared_sqft, measured_sqft=measured_sqft,
            tear_out_sqft=tear_out_sqft, room_count=room_count,
            product_overrides=product_overrides, clock=clock)
    api_client.start_install_slot(slot["id"], TEST_USERS["scheduler_headers"])
    slot = get_success_data(
        api_client.complete_install_slot(slot["id"], TEST_USERS["scheduler_headers"])
    )
    job = get_success_data(api_client.get_job(job["id"], TEST_USERS["admin_headers"]))
    return customer, sales_rep, product, job, crew, slot


# ─── Tier 4: Warranty claim ───────────────────────────────────────────

def create_filed_warranty_claim(declared_sqft=200, measured_sqft=200, tear_out_sqft=0,
                                room_count=1, product_overrides=None,
                                clock=DEFAULT_CLOCK, file_at=None,
                                defect_description="defect"):
    """COMPLETED job with one FILED WarrantyClaim filed by the owning customer.

    If file_at is given, the clock is advanced to it before filing so the claim's
    filed_at lands at that instant. Returns
    (customer, sales_rep, product, job, claim).
    """
    customer, sales_rep, product, job, crew, slot = create_completed_job(
        declared_sqft=declared_sqft, measured_sqft=measured_sqft,
        tear_out_sqft=tear_out_sqft, room_count=room_count,
        product_overrides=product_overrides, clock=clock,
    )
    if file_at is not None:
        set_clock(file_at)
    cust_headers = make_customer_headers(customer["id"])
    claim = get_success_data(api_client.create_warranty_claim(
        create_warranty_claim_payload(job["id"], defect_description=defect_description),
        cust_headers,
    ))
    return customer, sales_rep, product, job, claim


# ─── Tier 5: Threshold / accumulation targeting ───────────────────────

def setup_backordered_n_times(n, declared_sqft=200, measured_sqft=200,
                              tear_out_sqft=0, room_count=1, product_overrides=None,
                              clock=DEFAULT_CLOCK):
    """ACCEPTED job whose MaterialOrder has cycled through BACKORDERED n times.

    After the loop the order is back in ORDERED with backorder_count == n.
    Returns (customer, sales_rep, product, job, material_order).
    """
    customer, sales_rep, product, job, estimate, material_order = create_accepted_job(
        declared_sqft=declared_sqft, measured_sqft=measured_sqft,
        tear_out_sqft=tear_out_sqft, room_count=room_count,
        clock=clock, product_overrides=product_overrides,
    )
    sched = TEST_USERS["scheduler_headers"]
    for _ in range(n):
        api_client.backorder_material_order(material_order["id"], sched)
        material_order = get_success_data(
            api_client.reorder_material_order(material_order["id"], sched)
        )
    return customer, sales_rep, product, job, material_order


def add_accepted_job_for_customer(customer, sales_rep, product,
                                  declared_sqft=200, measured_sqft=200,
                                  tear_out_sqft=0, room_count=1,
                                  valid_until=FAR_FUTURE_VALID_UNTIL):
    """Open and drive ANOTHER job to ACCEPTED for existing actors + product.

    Used by capacity/overlap fixtures that need two accepted jobs sharing one
    crew. Returns (job, estimate, material_order).
    """
    rep_headers = make_sales_rep_headers(sales_rep["id"])
    cust_headers = make_customer_headers(customer["id"])
    job = get_success_data(api_client.create_job(
        create_job_payload(customer["id"], sales_rep["id"], product["id"],
                           declared_sqft=declared_sqft),
        rep_headers,
    ))
    job = get_success_data(api_client.measure_job(
        job["id"],
        measure_payload(measured_sqft=measured_sqft, tear_out_sqft=tear_out_sqft,
                        room_count=room_count),
        TEST_USERS["estimator_headers"],
    ))
    estimate = get_success_data(api_client.create_estimate(
        create_estimate_payload(job["id"], variant="MEASURED", valid_until=valid_until),
        rep_headers,
    ))
    estimate = get_success_data(api_client.issue_estimate(
        estimate["id"], issue_payload(job["version"]), rep_headers,
    ))
    estimate = get_success_data(api_client.accept_estimate(estimate["id"], cust_headers))
    job = get_success_data(api_client.get_job(job["id"], rep_headers))
    material_order = get_material_order_for_job(job["id"])
    return job, estimate, material_order


# ─── Internal ─────────────────────────────────────────────────────────

def _list(response):
    """Unwrap a paginated list response into (data_list, meta) leniently."""
    body = response.json()
    data = body.get("data", [])
    meta = body.get("meta", {})
    return data, meta
