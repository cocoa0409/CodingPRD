"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch via the public API (the test
harness restarts the server before every test, so each test starts against an
empty database). Setup calls use get_success_data() so a setup failure surfaces
as a clear "Setup failed" error rather than a confusing assertion failure.

Identity threading: after creating an entity-backed resource (Customer,
Subcontractor), any ownership- or assignee-gated call uses
make_customer_headers(entity["id"]) / make_subcontractor_headers(entity["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_ISO
from .factories import (
    SEA_MARKET, PDX_MARKET,
    board_scope_payload,
    create_coverage_payload,
    create_customer_payload,
    create_job_payload,
    create_market_payload,
    create_pdx_market_payload,
    create_property_payload,
    create_subcontractor_payload,
)
from .test_users import (
    TEST_USERS,
    make_customer_headers,
    make_subcontractor_headers,
)

ADMIN = TEST_USERS["admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


# ---------------------------------------------------------------------------
# Primitive step helpers (one API call each, success-asserted)
# ---------------------------------------------------------------------------

def create_market(overrides=None) -> dict:
    payload = create_market_payload(**(overrides or {}))
    return get_success_data(api_client.create_market(payload, ADMIN))


def create_pdx_market(overrides=None) -> dict:
    payload = create_pdx_market_payload(**(overrides or {}))
    return get_success_data(api_client.create_market(payload, ADMIN))


def onboard_subcontractor(legal_name="Alpha Board") -> dict:
    return get_success_data(
        api_client.create_subcontractor(create_subcontractor_payload(legal_name=legal_name), ADMIN)
    )


def grant_coverage(subcontractor_id, market_id, max_concurrent_jobs=2, rank=1) -> dict:
    payload = create_coverage_payload(
        subcontractor_id, market_id,
        max_concurrent_jobs=max_concurrent_jobs, rank=rank,
    )
    return get_success_data(api_client.create_coverage(payload, ADMIN))


def register_customer(**overrides) -> dict:
    return get_success_data(api_client.create_customer(create_customer_payload(**overrides), ADMIN))


def register_property(customer_id, market_id, **overrides) -> dict:
    payload = create_property_payload(customer_id, market_id, **overrides)
    return get_success_data(api_client.create_property(payload, ADMIN))


def intake_job(property_id, incident_type="FIRE", priority="P3", **extra) -> dict:
    payload = create_job_payload(property_id, incident_type=incident_type, priority=priority, **extra)
    return get_success_data(api_client.create_job(payload, DISPATCHER))


def get_job(job_id) -> dict:
    return get_success_data(api_client.get_job(job_id, DISPATCHER))


def get_subcontractor(subcontractor_id) -> dict:
    return get_success_data(api_client.get_subcontractor(subcontractor_id, DISPATCHER))


def get_assignment(assignment_id) -> dict:
    return get_success_data(api_client.get_assignment(assignment_id, DISPATCHER))


def dispatch_job(job_id, subcontractor_id=None) -> dict:
    """Dispatch (manual pin when subcontractor_id given, selector otherwise).
    Returns the created OFFERED assignment."""
    payload = {} if subcontractor_id is None else {"subcontractor_id": subcontractor_id}
    return get_success_data(api_client.dispatch_job(job_id, payload, DISPATCHER))


def accept_offer(assignment_id, subcontractor_id) -> dict:
    headers = make_subcontractor_headers(subcontractor_id)
    return get_success_data(
        api_client.respond_assignment(assignment_id, {"outcome": "ACCEPT"}, headers)
    )


def check_in_job(job_id, subcontractor_id) -> dict:
    return get_success_data(api_client.check_in_job(job_id, make_subcontractor_headers(subcontractor_id)))


def submit_assessment(job_id, assessor_id, hazards) -> dict:
    return get_success_data(
        api_client.create_safety_assessment(
            job_id, {"hazards": list(hazards)}, make_subcontractor_headers(assessor_id)
        )
    )


def mitigate_assessment(assessment_id, assessor_id, note="mitigated") -> dict:
    return get_success_data(
        api_client.mitigate_assessment(
            assessment_id, {"mitigation_note": note}, make_subcontractor_headers(assessor_id)
        )
    )


def add_scope_item(job_id, **fields) -> dict:
    """Add a scope line with a fresh OCC read of the job version."""
    job = get_job(job_id)
    payload = dict(fields)
    payload["expected_job_version"] = job["version"]
    return get_success_data(api_client.create_scope_item(job_id, payload, DISPATCHER))


def install_scope_item(scope_item_id, subcontractor_id, **measurements) -> dict:
    return get_success_data(
        api_client.install_scope_item(
            scope_item_id, measurements, make_subcontractor_headers(subcontractor_id)
        )
    )


def void_scope_item(scope_item_id) -> dict:
    return get_success_data(api_client.void_scope_item(scope_item_id, DISPATCHER))


def complete_securing(job_id, subcontractor_id) -> dict:
    return get_success_data(
        api_client.complete_securing(job_id, make_subcontractor_headers(subcontractor_id))
    )


def create_service(job_id, kind, starts_at, ends_at, generator_units=None) -> dict:
    payload = {"kind": kind, "starts_at": starts_at, "ends_at": ends_at}
    if generator_units is not None:
        payload["generator_units"] = generator_units
    return get_success_data(api_client.create_temporary_service(job_id, payload, DISPATCHER))


def deactivate_service(service_id) -> dict:
    return get_success_data(api_client.deactivate_service(service_id, DISPATCHER))


def schedule_visit(service_id, window_start, window_end) -> dict:
    payload = {"window_start": window_start, "window_end": window_end}
    return get_success_data(api_client.create_patrol_visit(service_id, payload, DISPATCHER))


def open_permit_case(job_id, kind) -> dict:
    return get_success_data(api_client.create_permit_case(job_id, {"kind": kind}, DISPATCHER))


def file_permit_case(permit_case_id, confirmation_number="CONF-001") -> dict:
    return get_success_data(
        api_client.file_permit_case(permit_case_id, {"confirmation_number": confirmation_number}, DISPATCHER)
    )


def record_permit_decision(permit_case_id, decision, decision_note=None) -> dict:
    payload = {"decision": decision}
    if decision_note is not None:
        payload["decision_note"] = decision_note
    return get_success_data(api_client.record_permit_decision(permit_case_id, payload, ADMIN))


def create_package(job_id) -> dict:
    return get_success_data(api_client.create_document_package(job_id, DISPATCHER))


def get_package(job_id) -> dict:
    """The job's single document package, read through the list endpoint."""
    data = get_success_data(api_client.list_document_packages(job_id, DISPATCHER))
    assert isinstance(data, list) and len(data) == 1, "expected exactly one document package"
    return data[0]


def add_artifact(job_id, package_id, kind) -> dict:
    """Add an artifact with a fresh OCC read of the package version."""
    pkg = get_package(job_id)
    payload = {"kind": kind, "expected_package_version": pkg["version"]}
    return get_success_data(api_client.add_artifact(package_id, payload, DISPATCHER))


def create_invoice(job_id, variant) -> dict:
    return get_success_data(api_client.create_invoice(job_id, {"variant": variant}, DISPATCHER))


def submit_invoice(invoice_id, variance_override=None) -> dict:
    payload = {}
    if variance_override is not None:
        payload["variance_override"] = variance_override
    return get_success_data(api_client.submit_invoice(invoice_id, payload, DISPATCHER))


def pay_invoice(invoice_id) -> dict:
    return get_success_data(api_client.record_payment(invoice_id, DISPATCHER))


def verify_repair(job_id, customer_id, outcome="VERIFIED") -> dict:
    return get_success_data(
        api_client.verify_repair(job_id, {"outcome": outcome}, make_customer_headers(customer_id))
    )


def record_removal(job_id, subcontractor_id) -> dict:
    return get_success_data(
        api_client.record_removal(job_id, make_subcontractor_headers(subcontractor_id))
    )


def close_job(job_id) -> dict:
    return get_success_data(api_client.close_job(job_id, DISPATCHER))


def set_clock(to_iso8601) -> dict:
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


# ---------------------------------------------------------------------------
# Tier 1/2: Network + job state progression composites
# ---------------------------------------------------------------------------

def setup_network(market_overrides=None, wind_zone="LOW", num_subcontractors=2,
                  covered_count=1, max_concurrent_jobs=2, address="1 Pine St",
                  market_preset="SEA"):
    """Market + subcontractors + coverage + customer + property.

    The first `covered_count` subcontractors receive coverage rows (ranks 1..n);
    the rest are uncovered (usable as segregated safety assessors).
    Returns dict(market, subs, customer, property).
    """
    if market_preset == "PDX":
        market = create_pdx_market(market_overrides)
    else:
        market = create_market(market_overrides)
    subs = []
    for i in range(num_subcontractors):
        subs.append(onboard_subcontractor(f"Crew {i + 1}"))
    for i in range(covered_count):
        grant_coverage(subs[i]["id"], market["id"],
                       max_concurrent_jobs=max_concurrent_jobs, rank=i + 1)
    customer = register_customer()
    prop = register_property(customer["id"], market["id"], wind_zone=wind_zone,
                             address_line=address)
    return {"market": market, "subs": subs, "customer": customer, "property": prop}


def setup_dispatched_job(priority="P3", incident_type="FIRE", wind_zone="LOW",
                         market_preset="SEA", market_overrides=None,
                         num_subcontractors=2, covered_count=1,
                         max_concurrent_jobs=2, pin=False):
    """Network + job in DISPATCHED with an OFFERED assignment.
    Returns ctx dict with keys market, subs, customer, property, job, assignment."""
    ctx = setup_network(market_overrides=market_overrides, wind_zone=wind_zone,
                        num_subcontractors=num_subcontractors,
                        covered_count=covered_count,
                        max_concurrent_jobs=max_concurrent_jobs,
                        market_preset=market_preset)
    job = intake_job(ctx["property"]["id"], incident_type=incident_type, priority=priority)
    pin_id = ctx["subs"][0]["id"] if pin else None
    assignment = dispatch_job(job["id"], subcontractor_id=pin_id)
    ctx["job"] = get_job(job["id"])
    ctx["assignment"] = assignment
    return ctx


def extend_dispatched_job(net, priority="P3", incident_type="FIRE", pin=False):
    """Add a fresh DISPATCHED job to an existing network context (shares the
    market, subcontractors, customer and property — required whenever one test
    needs several jobs, since the market code is unique)."""
    job = intake_job(net["property"]["id"], incident_type=incident_type, priority=priority)
    pin_id = net["subs"][0]["id"] if pin else None
    assignment = dispatch_job(job["id"], subcontractor_id=pin_id)
    ctx = dict(net)
    ctx["job"] = get_job(job["id"])
    ctx["assignment"] = assignment
    return ctx


def extend_on_site_job(net, hazards=("WATER",), with_assessment=True,
                       priority="P3", incident_type="FIRE", pin=False):
    """Add a job walked to ON_SITE (offer accepted + crew checked in) to an
    existing network. Optionally files a cleared low-hazard assessment by a
    subcontractor other than the assignee."""
    ctx = extend_dispatched_job(net, priority=priority, incident_type=incident_type,
                                pin=pin)
    assignee = next(s for s in net["subs"] if s["id"] == ctx["assignment"]["subcontractor_id"])
    ctx["assignee"] = assignee
    accept_offer(ctx["assignment"]["id"], assignee["id"])
    ctx["assignment"] = get_assignment(ctx["assignment"]["id"])
    check_in_job(ctx["job"]["id"], assignee["id"])
    ctx["job"] = get_job(ctx["job"]["id"])
    if with_assessment:
        assessor = next(s for s in net["subs"] if s["id"] != assignee["id"])
        ctx["assessor"] = assessor
        ctx["assessment"] = submit_assessment(ctx["job"]["id"], assessor["id"], hazards)
        ctx["job"] = get_job(ctx["job"]["id"])
    return ctx


def setup_on_site_job(priority="P3", incident_type="FIRE", wind_zone="LOW",
                      market_preset="SEA", market_overrides=None,
                      hazards=("WATER",), with_assessment=True,
                      num_subcontractors=2, covered_count=1, max_concurrent_jobs=2):
    """Dispatched job + offer accepted + crew checked in; optionally a cleared
    low-hazard assessment submitted by the second (uncovered) subcontractor.
    Returns ctx dict with keys market, subs, customer, property, job, assignment
    and (when with_assessment) assessment."""
    net = setup_network(market_overrides=market_overrides, wind_zone=wind_zone,
                        num_subcontractors=num_subcontractors,
                        covered_count=covered_count,
                        max_concurrent_jobs=max_concurrent_jobs,
                        market_preset=market_preset)
    return extend_on_site_job(net, hazards=hazards, with_assessment=with_assessment,
                              priority=priority, incident_type=incident_type)


DEFAULT_BOARD_SPEC = {"kind": "BOARD", "opening_count": 1, "width_in": 48,
                      "height_in": 36, "door_count": 0}


def extend_secured_job(net, scope_specs=None, install_specs=None, hazards=("WATER",),
                       priority="P3", incident_type="FIRE"):
    """Add a job walked all the way to SECURED on an existing network:
    on-site job + scope items added, installed, and securing completed."""
    if scope_specs is None:
        scope_specs = [dict(DEFAULT_BOARD_SPEC)]
    if install_specs is None:
        install_specs = [{k: v for k, v in spec.items() if k != "kind"} for spec in scope_specs]
    ctx = extend_on_site_job(net, hazards=hazards, with_assessment=True,
                             priority=priority, incident_type=incident_type)
    scope_items = []
    for spec, install in zip(scope_specs, install_specs):
        item = add_scope_item(ctx["job"]["id"], **spec)
        installed = install_scope_item(item["id"], ctx["assignee"]["id"], **install)
        scope_items.append(installed)
    ctx["scope_items"] = scope_items
    complete_securing(ctx["job"]["id"], ctx["assignee"]["id"])
    ctx["job"] = get_job(ctx["job"]["id"])
    return ctx


def setup_secured_job(priority="P3", incident_type="FIRE", wind_zone="LOW",
                      market_preset="SEA", market_overrides=None,
                      scope_specs=None, install_specs=None, hazards=("WATER",),
                      num_subcontractors=2, covered_count=1, max_concurrent_jobs=2):
    """Full progression to SECURED: on-site job + scope items added, installed,
    and securing completed by the assignee.

    scope_specs: list of scope-add field dicts (default: one 1-opening BOARD).
    install_specs: list of install measurement dicts (default: same as scope_specs).
    Returns ctx dict with keys market, subs, customer, property, job, assignment,
    assignee, assessor, assessment, scope_items.
    """
    net = setup_network(market_overrides=market_overrides, wind_zone=wind_zone,
                        num_subcontractors=num_subcontractors,
                        covered_count=covered_count,
                        max_concurrent_jobs=max_concurrent_jobs,
                        market_preset=market_preset)
    return extend_secured_job(net, scope_specs=scope_specs, install_specs=install_specs,
                              hazards=hazards, priority=priority, incident_type=incident_type)


# ---------------------------------------------------------------------------
# Tier 3: Billing lifecycle shortcuts
# ---------------------------------------------------------------------------

def approve_permit(ctx, confirmation_number="SEA-P-001") -> dict:
    """Open, file and APPROVE a PERMIT case for the context's job."""
    case = open_permit_case(ctx["job"]["id"], "PERMIT")
    file_permit_case(case["id"], confirmation_number)
    return record_permit_decision(case["id"], "APPROVED")


def file_notification(ctx, confirmation_number="SEA-N-001") -> dict:
    """Open and file a NOTIFICATION case for the context's job (on time at the
    current clock). Returns the FILED case."""
    case = open_permit_case(ctx["job"]["id"], "NOTIFICATION")
    return file_permit_case(case["id"], confirmation_number)


def setup_complete_package(ctx, photo_count=None) -> dict:
    """Create the job's document package and add artifacts until COMPLETE:
    `photo_count` PHOTO artifacts (default: the package's required_photo_count),
    then AUTHORIZATION and MEASUREMENT_SHEET. Returns the package."""
    pkg = create_package(ctx["job"]["id"])
    if photo_count is None:
        photo_count = pkg["required_photo_count"]
    for _ in range(photo_count):
        pkg = add_artifact(ctx["job"]["id"], pkg["id"], "PHOTO")
    pkg = add_artifact(ctx["job"]["id"], pkg["id"], "AUTHORIZATION")
    pkg = add_artifact(ctx["job"]["id"], pkg["id"], "MEASUREMENT_SHEET")
    ctx["package"] = pkg
    return pkg


def create_submitted_invoice(ctx, variant="PROVISIONAL", variance_override=None) -> dict:
    invoice = create_invoice(ctx["job"]["id"], variant)
    return submit_invoice(invoice["id"], variance_override=variance_override)


def create_paid_invoice(ctx, variant="PROVISIONAL", variance_override=None) -> dict:
    invoice = create_submitted_invoice(ctx, variant, variance_override=variance_override)
    return pay_invoice(invoice["id"])


def setup_billing_ready(ctx, with_permit=True, with_notification=True) -> dict:
    """For a SECURED job: approve the permit and complete the document package,
    and (optionally) file the notification on time. Returns the package."""
    if with_permit:
        ctx["permit_case"] = approve_permit(ctx)
    pkg = setup_complete_package(ctx)
    if with_notification:
        ctx["notification_case"] = file_notification(ctx)
    return pkg


def setup_removed_job(priority="P3", market_preset="SEA", wind_zone="LOW",
                      scope_specs=None, install_specs=None,
                      with_permit=True, with_notification=True,
                      incident_type="FIRE"):
    """SECURED job with billing prereqs satisfied, provisional invoice PAID,
    repair VERIFIED and removal recorded. Returns ctx with job REMOVED."""
    ctx = setup_secured_job(priority=priority, incident_type=incident_type,
                            wind_zone=wind_zone, market_preset=market_preset,
                            scope_specs=scope_specs, install_specs=install_specs)
    setup_billing_ready(ctx, with_permit=with_permit, with_notification=with_notification)
    ctx["provisional_invoice"] = create_paid_invoice(ctx, "PROVISIONAL")
    verify_repair(ctx["job"]["id"], ctx["customer"]["id"], "VERIFIED")
    record_removal(ctx["job"]["id"], ctx["assignee"]["id"])
    ctx["job"] = get_job(ctx["job"]["id"])
    return ctx


def setup_closed_job(priority="P3", market_preset="PDX", wind_zone="LOW"):
    """Entire lifecycle through CLOSED: secure -> bill -> pay -> verify ->
    remove -> final bill -> pay -> close. Returns ctx with job CLOSED."""
    ctx = setup_removed_job(priority=priority, market_preset=market_preset,
                            wind_zone=wind_zone,
                            with_permit=False, with_notification=False)
    ctx["final_invoice"] = create_paid_invoice(ctx, "FINAL")
    close_job(ctx["job"]["id"])
    ctx["job"] = get_job(ctx["job"]["id"])
    return ctx
