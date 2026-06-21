"""Composite setup helpers.

Each test runs against a fresh, empty database (the harness restarts the server
before every test), so every helper builds its preconditions from scratch using
only PRD-declared endpoints. Helpers use get_success_data() (lenient) internally
so setup failures surface as clear "Setup failed" errors.

Identity threading: Customer and Technician are entity-backed roles, so any
ownership-gated call uses make_customer_headers(customer["id"]) /
make_technician_headers(technician["id"]) with the real entity id.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_customer_payload,
    create_technician_payload,
    create_door_model_payload,
    create_opener_model_payload,
    create_part_payload,
    create_equipment_unit_payload,
    create_quote_payload,
    create_quote_line_payload,
    schedule_job_payload,
    create_warranty_plan_payload,
    create_financing_application_payload,
    create_callback_payload,
    resolve_callback_payload,
)
from .test_users import (
    TEST_USERS,
    make_customer_headers,
    make_technician_headers,
    make_dispatcher_headers,
    make_service_manager_headers,
)

SM = TEST_USERS["service_manager_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]

# A fixed UTC instant used as the server "now" so SENT quotes do not expire
# during multi-step setups and scheduled windows land in the future.
DEFAULT_CLOCK = "2026-06-15T12:00:00Z"
# Default scheduling window (UTC). 17:00Z = 10:00 Phoenix local = BUSINESS band.
DEFAULT_START = "2026-07-01T17:00:00Z"
DEFAULT_END = "2026-07-01T18:00:00Z"


# ---------------------------------------------------------------------------
# Primitive creators
# ---------------------------------------------------------------------------
def create_customer(**overrides) -> dict:
    resp = api_client.create_customer(create_customer_payload(**overrides), SM)
    return get_success_data(resp)


def create_technician(**overrides) -> dict:
    resp = api_client.create_technician(create_technician_payload(**overrides), SM)
    return get_success_data(resp)


def create_door_model(**overrides) -> dict:
    resp = api_client.create_door_model(create_door_model_payload(**overrides), SM)
    return get_success_data(resp)


def create_opener_model(**overrides) -> dict:
    resp = api_client.create_opener_model(create_opener_model_payload(**overrides), SM)
    return get_success_data(resp)


def create_part(**overrides) -> dict:
    resp = api_client.create_part(create_part_payload(**overrides), SM)
    return get_success_data(resp)


def create_equipment_unit(**overrides) -> dict:
    resp = api_client.create_equipment_unit(create_equipment_unit_payload(**overrides), SM)
    return get_success_data(resp)


def set_clock(to_iso8601: str):
    return get_success_data(api_client.set_current_utc({"to_iso8601": to_iso8601}, SM))


# ---------------------------------------------------------------------------
# Tier 1/2: Quotes and lines
# ---------------------------------------------------------------------------
def create_quote(customer_id, **overrides) -> dict:
    resp = api_client.create_quote(create_quote_payload(customer_id, **overrides), SM)
    return get_success_data(resp)


def add_line(quote_id, item_kind, **overrides) -> dict:
    resp = api_client.add_quote_line(quote_id, create_quote_line_payload(item_kind, **overrides), SM)
    return get_success_data(resp)


def create_sent_quote(customer_id, lines, **quote_overrides) -> dict:
    """Create a quote, add each line, and send it. `lines` is a list of dicts:
    {"item_kind": "...", ...other line fields}. Returns the SENT quote object."""
    quote = create_quote(customer_id, **quote_overrides)
    for line in lines:
        kind = line["item_kind"]
        rest = {k: v for k, v in line.items() if k != "item_kind"}
        add_line(quote["id"], kind, **rest)
    return get_success_data(api_client.send_quote(quote["id"], SM))


def accept_quote_get_job(quote_id, customer_id) -> dict:
    """Customer accepts the quote (ownership-gated) and returns the spawned Job."""
    cust_headers = make_customer_headers(customer_id)
    get_success_data(api_client.accept_quote(quote_id, cust_headers))
    jobs, _meta = _list_jobs_by_quote(quote_id)
    assert jobs, f"Setup failed: no job spawned for accepted quote {quote_id}"
    return jobs[0]


def _list_jobs_by_quote(quote_id):
    from prd_bench_local_runner.testing import validate_paginated
    resp = api_client.list_jobs(SM, params={"quote_id": quote_id})
    # get_success_data also works for arrays, but we want the data list here.
    return validate_paginated(resp)


# ---------------------------------------------------------------------------
# Tier 2/3: Jobs through the dispatch lifecycle
# ---------------------------------------------------------------------------
def setup_accepted_job(
    *,
    quote_type="SERVICE_CALL",
    service_call_fee_cents=5000,
    lines=None,
    door_model_id=None,
    opener_model_id=None,
    time_zone=None,
) -> dict:
    """Customer + SENT quote (with given lines) + accept. Returns
    {customer, technician, quote, job}. A CERTIFIED install-capable technician
    is always created so callers can schedule either SERVICE_CALL or INSTALL."""
    cust_kwargs = {}
    if time_zone is not None:
        cust_kwargs["time_zone"] = time_zone
    customer = create_customer(**cust_kwargs)
    technician = create_technician()
    quote_overrides = {"quote_type": quote_type}
    if quote_type == "SERVICE_CALL":
        quote_overrides["service_call_fee_cents"] = service_call_fee_cents
    else:
        if door_model_id is not None:
            quote_overrides["door_model_id"] = door_model_id
        if opener_model_id is not None:
            quote_overrides["opener_model_id"] = opener_model_id
    if lines is None:
        lines = [{"item_kind": "LABOR", "qty": 30}]
    quote = create_sent_quote(customer["id"], lines, **quote_overrides)
    job = accept_quote_get_job(quote["id"], customer["id"])
    return {"customer": customer, "technician": technician, "quote": quote, "job": job}


def schedule_job(job_id, technician_id, *, start=DEFAULT_START, end=DEFAULT_END, **overrides) -> dict:
    resp = api_client.schedule_job(
        job_id,
        schedule_job_payload(technician_id, start, end, **overrides),
        DISPATCHER,
    )
    return get_success_data(resp)


def setup_scheduled_job(*, start=DEFAULT_START, end=DEFAULT_END, **accepted_overrides) -> dict:
    ctx = setup_accepted_job(**accepted_overrides)
    ctx["job"] = schedule_job(ctx["job"]["id"], ctx["technician"]["id"], start=start, end=end)
    return ctx


def setup_on_site_job(*, start=DEFAULT_START, end=DEFAULT_END, **accepted_overrides) -> dict:
    """Walk a job to ON_SITE (scheduled -> depart -> arrive)."""
    ctx = setup_scheduled_job(start=start, end=end, **accepted_overrides)
    tech_h = make_technician_headers(ctx["technician"]["id"])
    get_success_data(api_client.depart_job(ctx["job"]["id"], tech_h))
    ctx["job"] = get_success_data(api_client.arrive_job(ctx["job"]["id"], tech_h))
    return ctx


def consume_all_reservations(job_id, technician_id):
    """Consume every HELD reservation on the job (parent must be ON_SITE)."""
    from prd_bench_local_runner.testing import validate_paginated
    tech_h = make_technician_headers(technician_id)
    resp = api_client.list_part_reservations(SM, params={"job_id": job_id})
    reservations, _ = validate_paginated(resp)
    for r in reservations:
        if r["status"] == "HELD":
            get_success_data(api_client.consume_part_reservation(r["id"], tech_h))


def setup_completed_job(
    *,
    start=DEFAULT_START,
    end=DEFAULT_END,
    is_emergency=False,
    pass_safety=True,
    consume_parts=True,
    **accepted_overrides,
) -> dict:
    """Full path to dispatch_status COMPLETED. Returns {customer, technician,
    quote, job}. The job dict is the response of /complete."""
    sched_overrides = {}
    if is_emergency:
        sched_overrides["is_emergency"] = True
    ctx = setup_accepted_job(**accepted_overrides)
    # Schedule (carry equipment if the door requires a lift handled by caller).
    ctx["job"] = schedule_job(
        ctx["job"]["id"], ctx["technician"]["id"], start=start, end=end, **sched_overrides
    )
    tech_h = make_technician_headers(ctx["technician"]["id"])
    get_success_data(api_client.depart_job(ctx["job"]["id"], tech_h))
    get_success_data(api_client.arrive_job(ctx["job"]["id"], tech_h))
    if consume_parts:
        consume_all_reservations(ctx["job"]["id"], ctx["technician"]["id"])
    if pass_safety:
        get_success_data(api_client.safety_check_job(ctx["job"]["id"], tech_h))
    ctx["job"] = get_success_data(api_client.complete_job(ctx["job"]["id"], tech_h))
    return ctx


def setup_paid_job(*, manager_id="manager-1", **completed_overrides) -> dict:
    """COMPLETED -> INVOICED -> PAID. Invoicer manager id differs from the
    completing technician id by default, satisfying segregation of duties."""
    ctx = setup_completed_job(**completed_overrides)
    mgr_h = make_service_manager_headers(manager_id)
    get_success_data(api_client.invoice_job(ctx["job"]["id"], mgr_h))
    ctx["job"] = get_success_data(api_client.pay_job(ctx["job"]["id"], mgr_h))
    return ctx


def setup_closed_job(*, manager_id="manager-1", **completed_overrides) -> dict:
    """COMPLETED -> INVOICED -> PAID -> CLOSED."""
    ctx = setup_paid_job(manager_id=manager_id, **completed_overrides)
    mgr_h = make_service_manager_headers(manager_id)
    ctx["job"] = get_success_data(api_client.close_job(ctx["job"]["id"], mgr_h))
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: Warranty / financing / callback composites
# ---------------------------------------------------------------------------
def create_warranty_plan(job_id, customer_id, **overrides) -> dict:
    resp = api_client.create_warranty_plan(
        create_warranty_plan_payload(job_id, customer_id, **overrides), SM
    )
    return get_success_data(resp)


def setup_closed_job_with_active_warranty(*, tune_ups_included=2, manager_id="manager-1") -> dict:
    """Completed+paid job whose PENDING warranty plan is activated on close.
    Returns {customer, technician, quote, job, warranty_plan}."""
    ctx = setup_completed_job(time_zone="America/Phoenix")
    plan = create_warranty_plan(
        ctx["job"]["id"], ctx["customer"]["id"], tune_ups_included=tune_ups_included
    )
    mgr_h = make_service_manager_headers(manager_id)
    get_success_data(api_client.invoice_job(ctx["job"]["id"], mgr_h))
    get_success_data(api_client.pay_job(ctx["job"]["id"], mgr_h))
    ctx["job"] = get_success_data(api_client.close_job(ctx["job"]["id"], mgr_h))
    ctx["warranty_plan"] = get_success_data(api_client.get_warranty_plan(plan["id"], SM))
    return ctx


def submit_financing_application(customer_id, quote_id, principal_cents, term_months) -> dict:
    resp = api_client.create_financing_application(
        create_financing_application_payload(customer_id, quote_id, principal_cents, term_months),
        SM,
    )
    return get_success_data(resp)


def setup_blocked_customer() -> dict:
    """Customer with a DEFAULTED financing application (financing_standing
    BLOCKED) plus a separate SENT quote ready to accept. Returns
    {customer, blocked_quote}."""
    customer = create_customer()
    # First quote: financed, accepted, then defaulted to block the customer.
    fin_quote = create_sent_quote(
        customer["id"], [{"item_kind": "LABOR", "qty": 30}], service_call_fee_cents=5000
    )
    app = submit_financing_application(customer["id"], fin_quote["id"], fin_quote["estimate_total_cents"], 12)
    get_success_data(api_client.approve_financing_application(app["id"], SM))
    get_success_data(api_client.accept_quote(fin_quote["id"], make_customer_headers(customer["id"])))
    get_success_data(api_client.activate_financing_application(app["id"], SM))
    get_success_data(api_client.default_financing_application(app["id"], SM))
    # Second quote: SENT, ready to test the blocked-accept path.
    blocked_quote = create_sent_quote(
        customer["id"], [{"item_kind": "LABOR", "qty": 30}], service_call_fee_cents=5000
    )
    return {"customer": customer, "blocked_quote": blocked_quote}


def open_callback(job_id, customer_id, reason="Test callback") -> dict:
    resp = api_client.create_callback(
        create_callback_payload(job_id, reason=reason), make_customer_headers(customer_id)
    )
    return get_success_data(resp)


def setup_on_site_callback() -> dict:
    """A callback on a completed job walked to ON_SITE. Returns
    {customer, technician, quote, job, callback}."""
    ctx = setup_completed_job(time_zone="America/Phoenix")
    cb = open_callback(ctx["job"]["id"], ctx["customer"]["id"], reason="noise")
    get_success_data(api_client.schedule_callback(cb["id"], DISPATCHER))
    tech_h = make_technician_headers(ctx["technician"]["id"])
    ctx["callback"] = get_success_data(api_client.arrive_callback(cb["id"], tech_h))
    return ctx


def get_job(job_id) -> dict:
    return get_success_data(api_client.get_job(job_id, SM))


def get_part(part_id) -> dict:
    return get_success_data(api_client.get_part(part_id, SM))


def get_technician(technician_id) -> dict:
    return get_success_data(api_client.get_technician(technician_id, SM))


def get_customer(customer_id) -> dict:
    return get_success_data(api_client.get_customer(customer_id, SM))


def first_reservation(job_id) -> dict:
    from prd_bench_local_runner.testing import validate_paginated
    resp = api_client.list_part_reservations(SM, params={"job_id": job_id})
    reservations, _ = validate_paginated(resp)
    assert reservations, f"Setup failed: no reservations for job {job_id}"
    return reservations[0]
