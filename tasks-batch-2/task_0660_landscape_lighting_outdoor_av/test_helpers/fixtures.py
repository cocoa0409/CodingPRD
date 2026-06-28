"""Composite setup helpers.

These encapsulate the multi-step preambles every interesting test needs. The
recurring spine is: register a customer, open a project, stage a transformer,
zone it, plan+assign fixtures, lock the design, quote+send+accept, then run an
install job through to ENERGIZED — which flips the project to INSTALLED and the
fixtures to INSTALLED. Helpers return dicts of captured ids/versions so tests
can assert against the exact resources they built.

Setup calls use get_success_data() (lenient) so a broken precondition surfaces
as a clear "Setup failed" rather than a confusing assertion later. Ownership-
gated Customer calls thread the real Customer.id via make_customer_headers().
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_customer_headers
from . import factories as F


DESIGNER = TEST_USERS["lighting_designer_headers"]
TECH = TEST_USERS["install_tech_headers"]
PROGRAMMER = TEST_USERS["control_programmer_headers"]
ADMIN = TEST_USERS["operations_admin_headers"]


# ---------------------------------------------------------------------------
# Clock control
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str):
    """Advance the logical clock (OperationsAdmin)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ---------------------------------------------------------------------------
# Primitive creators (single-call, returning the data dict)
# ---------------------------------------------------------------------------
def create_customer(**overrides) -> dict:
    return get_success_data(api_client.create_customer(F.create_customer_payload(**overrides), ADMIN))


def create_project(customer_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_project(F.create_project_payload(customer_id, **overrides), ADMIN)
    )


def create_transformer(project_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_transformer(F.create_transformer_payload(project_id, **overrides), DESIGNER)
    )


def create_zone(project_id: str, transformer_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_zone(project_id, F.create_zone_payload(transformer_id, **overrides), DESIGNER)
    )


def create_fixture(project_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_fixture(F.create_fixture_payload(project_id, **overrides), DESIGNER)
    )


def assign_fixture(fixture_id: str, zone_id: str, expected_transformer_version: int) -> dict:
    return get_success_data(
        api_client.assign_zone(
            fixture_id,
            F.assign_zone_payload(zone_id, expected_transformer_version),
            DESIGNER,
        )
    )


# ---------------------------------------------------------------------------
# Tier 1/2: project + transformer + zone, plus zoned + design-locked variants
# ---------------------------------------------------------------------------
def setup_project_with_transformer_and_zone(rated_capacity_va: int = 300):
    """Customer -> project (DRAFT/PRE_QUOTE) -> transformer (STAGED) -> first zone
    (project now ZONED). Returns dict with cust, project, transformer, transformer
    current version, and zone."""
    cust = create_customer()
    project = create_project(cust["id"])
    tx = create_transformer(project["id"], rated_capacity_va=rated_capacity_va)
    zone = create_zone(project["id"], tx["id"])
    return {
        "customer": cust,
        "cust_id": cust["id"],
        "project": project,
        "project_id": project["id"],
        "transformer": tx,
        "tx_id": tx["id"],
        "tx_version": tx["version"],
        "zone": zone,
        "zone_id": zone["id"],
    }


def assign_fixtures_to_zone(ctx: dict, fixture_specs: list) -> list:
    """Create + assign a list of fixtures to ctx['zone_id'], threading the
    transformer version forward across assignments. Each spec is a dict of
    create_fixture overrides (must include wattage_w). Returns the list of
    assigned fixture dicts. Updates ctx['tx_version'] to the latest version.

    Reads the live transformer version before the first assign so the chain is
    correct regardless of prior mutations."""
    fixtures = []
    tx = get_success_data(api_client.get_transformer(ctx["tx_id"], DESIGNER))
    version = tx["version"]
    for spec in fixture_specs:
        fx = create_fixture(ctx["project_id"], **spec)
        assigned = assign_fixture(fx["id"], ctx["zone_id"], version)
        fixtures.append(assigned)
        # assign-zone returns the Fixture, not the transformer; the assign bumps
        # the transformer version by one, so re-read it for the next assignment.
        tx = get_success_data(api_client.get_transformer(ctx["tx_id"], DESIGNER))
        version = tx["version"]
    ctx["tx_version"] = version
    return fixtures


def lock_design(project_id: str) -> dict:
    return get_success_data(api_client.lock_design(project_id, DESIGNER))


# ---------------------------------------------------------------------------
# Tier 3: quote lifecycle shortcuts
# ---------------------------------------------------------------------------
def build_draft_quote_with_lines(project_id: str, lines: list, quote_overrides: dict = None) -> dict:
    """Create a DRAFT quote and add the given lines. Each line is a dict of
    add_quote_line overrides. Returns the quote dict (pre-send)."""
    quote = get_success_data(
        api_client.create_quote(F.create_quote_payload(project_id, **(quote_overrides or {})), DESIGNER)
    )
    for line in lines:
        get_success_data(api_client.add_quote_line(quote["id"], F.create_quote_line_payload(**line), DESIGNER))
    return quote


def send_quote(quote_id: str) -> dict:
    return get_success_data(api_client.send_quote(quote_id, DESIGNER))


def accept_quote(quote_id: str, customer_id: str) -> dict:
    return get_success_data(api_client.accept_quote(quote_id, make_customer_headers(customer_id)))


def setup_accepted_quote(ctx: dict, lines: list = None, quote_overrides: dict = None) -> dict:
    """From a project that already has at least one assigned fixture, lock the
    design, build a quote with `lines`, send it, and have the customer accept it.
    The project ends at commercial_status ACCEPTED. Returns ctx augmented with the
    quote. Assumes ctx has 'project_id' and 'cust_id'."""
    if lines is None:
        lines = [{"model_code": "PATH-3W", "quantity": 1, "unit_price_cents": 4000}]
    lock_design(ctx["project_id"])
    quote = build_draft_quote_with_lines(ctx["project_id"], lines, quote_overrides)
    send_quote(quote["id"])
    accept_quote(quote["id"], ctx["cust_id"])
    ctx["quote"] = quote
    ctx["quote_id"] = quote["id"]
    return ctx


# ---------------------------------------------------------------------------
# Tier 3/5: install job through to ENERGIZED (project -> INSTALLED)
# ---------------------------------------------------------------------------
def run_install_to_energized(ctx: dict) -> dict:
    """Create an install job against ctx['quote_id'], start it, complete wiring
    (energizes staged transformers) and complete fixtures (mounts planned zoned
    fixtures; join -> project INSTALLED). Returns ctx augmented with the energized
    install job."""
    job = get_success_data(
        api_client.create_install_job(F.create_install_job_payload(ctx["project_id"], ctx["quote_id"]), TECH)
    )
    get_success_data(api_client.start_install_job(job["id"], TECH))
    get_success_data(api_client.complete_wiring(job["id"], TECH))
    get_success_data(api_client.complete_fixtures(job["id"], TECH))
    ctx["job"] = job
    ctx["job_id"] = job["id"]
    return ctx


def setup_installed_project(rated_capacity_va: int = 300, fixture_specs: list = None,
                            quote_lines: list = None):
    """Full spine to an INSTALLED project with INSTALLED fixtures.

    Builds: customer -> project -> transformer -> zone -> fixtures (assigned) ->
    lock design -> quote (lines) -> send -> accept -> install job -> ENERGIZED.

    fixture_specs default to a single PATH-3W 3W fixture. quote_lines default to
    one line covering it. Returns the ctx dict with everything captured plus
    'fixtures' (the assigned, now-INSTALLED fixtures)."""
    if fixture_specs is None:
        fixture_specs = [{"model_code": "PATH-3W", "category": "PATH", "wattage_w": 3,
                          "purchase_price_cents": 4000}]
    if quote_lines is None:
        quote_lines = [{"model_code": "PATH-3W", "quantity": 1, "unit_price_cents": 4000}]
    ctx = setup_project_with_transformer_and_zone(rated_capacity_va=rated_capacity_va)
    ctx["fixtures"] = assign_fixtures_to_zone(ctx, fixture_specs)
    setup_accepted_quote(ctx, lines=quote_lines)
    run_install_to_energized(ctx)
    # Refresh the now-INSTALLED fixtures.
    ctx["fixtures"] = [get_success_data(api_client.get_fixture(fx["id"], DESIGNER)) for fx in ctx["fixtures"]]
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: capacity boundary targeting
# ---------------------------------------------------------------------------
def setup_zone_near_capacity(filled_specs: list, rated_capacity_va: int = 300):
    """Project + transformer + zone with `filled_specs` fixtures already assigned
    (still PLANNED, design not locked). Used for capacity-boundary and OCC tests.
    Returns ctx with 'fixtures' (assigned) and ctx['tx_version'] = current version.
    """
    ctx = setup_project_with_transformer_and_zone(rated_capacity_va=rated_capacity_va)
    ctx["fixtures"] = assign_fixtures_to_zone(ctx, filled_specs)
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: active service plan on an installed project
# ---------------------------------------------------------------------------
def setup_active_service_plan(ctx: dict = None, plan_overrides: dict = None,
                              rated_capacity_va: int = 300):
    """Ensure an INSTALLED project, then create + activate a service plan.
    If ctx is None a fresh installed project is built. Returns ctx augmented
    with 'plan' (ACTIVE). plan_overrides feed create_service_plan_payload."""
    if ctx is None:
        ctx = setup_installed_project(rated_capacity_va=rated_capacity_va)
    plan = get_success_data(
        api_client.create_service_plan(
            F.create_service_plan_payload(ctx["project_id"], **(plan_overrides or {})), ADMIN
        )
    )
    get_success_data(api_client.activate_service_plan(plan["id"], make_customer_headers(ctx["cust_id"])))
    ctx["plan"] = plan
    ctx["plan_id"] = plan["id"]
    return ctx


def create_pending_service_plan(ctx: dict, plan_overrides: dict = None) -> dict:
    """Create a PENDING (not activated) service plan on ctx's project."""
    plan = get_success_data(
        api_client.create_service_plan(
            F.create_service_plan_payload(ctx["project_id"], **(plan_overrides or {})), ADMIN
        )
    )
    ctx["plan"] = plan
    ctx["plan_id"] = plan["id"]
    return ctx


def request_service_visit(ctx: dict, **visit_overrides) -> dict:
    """Request a service visit under ctx['plan_id'] for ctx's project (InstallTech)."""
    visit = get_success_data(
        api_client.create_service_visit(
            F.create_service_visit_payload(ctx["plan_id"], ctx["project_id"], **visit_overrides), TECH
        )
    )
    return visit


# ---------------------------------------------------------------------------
# Warranty: submit a claim (fixture INSTALLED -> FAILED)
# ---------------------------------------------------------------------------
def submit_warranty_claim(ctx: dict, fixture_id: str, **overrides) -> dict:
    """Customer submits a warranty claim against an INSTALLED fixture, which
    cascades the fixture to FAILED."""
    claim = get_success_data(
        api_client.create_warranty_claim(
            F.create_warranty_claim_payload(fixture_id, ctx["project_id"], **overrides),
            make_customer_headers(ctx["cust_id"]),
        )
    )
    return claim


# ---------------------------------------------------------------------------
# Schedule programs on an installed project
# ---------------------------------------------------------------------------
def create_schedule_program(ctx: dict, **overrides) -> dict:
    return get_success_data(
        api_client.create_schedule_program(
            F.create_schedule_program_payload(ctx["project_id"], **overrides), PROGRAMMER
        )
    )


def activate_schedule_program(program_id: str) -> dict:
    return get_success_data(api_client.activate_schedule_program(program_id, PROGRAMMER))
