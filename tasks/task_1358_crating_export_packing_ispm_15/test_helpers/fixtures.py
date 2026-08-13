"""
Composite setup helpers for multi-step test prerequisites.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (the server restarts before each test, so each test starts against
an empty database). Helpers use get_success_data() (lenient validator) so a
setup failure surfaces as a clear "Setup failed" style error rather than a
confusing assertion failure inside a test body.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_customer_payload, create_packing_job_payload, create_item_payload,
    create_design_payload, approve_design_payload, create_wood_batch_payload,
    create_crate_payload, pack_crate_payload, create_hazmat_declaration_payload,
    packing_list_line, create_packing_list_payload,
    invoice_line, create_commercial_invoice_payload,
    create_crew_payload, create_labor_booking_payload,
    create_onsite_permit_payload, create_container_payload, create_claim_payload,
)
from .test_users import TEST_USERS, make_customer_headers

SR = TEST_USERS["sales_rep_headers"]
CD = TEST_USERS["crating_designer_headers"]
SF = TEST_USERS["shop_foreman_headers"]
CO = TEST_USERS["compliance_officer_headers"]
LC = TEST_USERS["logistics_coordinator_headers"]
ADJ = TEST_USERS["claims_adjuster_headers"]
PA = TEST_USERS["platform_admin_headers"]

# Protection payload that matches a STANDARD item's design requirements
# (indicator 75G, no moisture barrier).
STD_PACK = {"indicator_g": 75, "moisture_barrier": "NONE"}


def _customer_headers(customer: dict) -> dict:
    """Ownership-gated Customer calls must carry the real Customer.id."""
    return make_customer_headers(customer["id"])


# ─── Tier 1: State Progression ─────────────────────────────────────────────

def create_customer(**overrides):
    """Create an ACTIVE customer. Returns the Customer."""
    return get_success_data(api_client.create_customer(create_customer_payload(**overrides), SR))


def create_job(customer: dict, mode: str = "SHOP", incoterm: str = "FOB"):
    """Create a QUOTED packing job for the customer. Returns the PackingJob."""
    return get_success_data(api_client.create_packing_job(
        create_packing_job_payload(customer["id"], mode=mode, incoterm=incoterm), SR))


def add_item(job_id: str, **overrides):
    """Capture an item on a QUOTED job. Returns the Item."""
    return get_success_data(api_client.create_item(job_id, create_item_payload(**overrides), SR))


def create_wood_batch(**overrides):
    """Register an ACTIVE ISPM-15 wood batch. Returns the WoodBatch."""
    return get_success_data(api_client.create_wood_batch(create_wood_batch_payload(**overrides), CO))


def submit_and_approve_design(design_id: str, wood_batch_id: str):
    """DRAFT -> IN_REVIEW -> APPROVED, pinning the batch. Returns the design."""
    get_success_data(api_client.submit_design(design_id, CD))
    return get_success_data(api_client.approve_design(
        design_id, approve_design_payload(wood_batch_id), CO))


def accept_quote(customer: dict, job_id: str):
    """Customer accepts the quote (QUOTED -> DESIGN). Ownership-threaded."""
    return get_success_data(api_client.accept_quote(job_id, _customer_headers(customer)))


def start_packing(job_id: str):
    """DESIGN -> PACKING. Returns the PackingJob."""
    return get_success_data(api_client.start_packing(job_id, SF))


# ─── Tier 2: Entity Hierarchy ──────────────────────────────────────────────

def setup_quoted_job_with_item(mode: str = "SHOP", incoterm: str = "FOB",
                               item_overrides: dict | None = None,
                               customer_overrides: dict | None = None):
    """Customer + QUOTED job + one captured item. Returns (customer, job, item)."""
    customer = create_customer(**(customer_overrides or {}))
    job = create_job(customer, mode=mode, incoterm=incoterm)
    item = add_item(job["id"], **(item_overrides or {}))
    return customer, job, item


def setup_job_with_approved_design(mode: str = "SHOP", incoterm: str = "FOB",
                                   item_overrides: dict | None = None,
                                   batch_overrides: dict | None = None,
                                   customer_overrides: dict | None = None,
                                   accept: bool = False):
    """
    Customer + QUOTED job + item + APPROVED CrateDesign on a wood batch.
    When accept=True the quote is also accepted (job moves to DESIGN).
    Returns dict(customer, job, item, batch, design).
    """
    customer, job, item = setup_quoted_job_with_item(
        mode=mode, incoterm=incoterm,
        item_overrides=item_overrides, customer_overrides=customer_overrides)
    batch = create_wood_batch(**(batch_overrides or {}))
    design = get_success_data(api_client.create_design(
        item["id"], create_design_payload(item["version"]), CD))
    design = submit_and_approve_design(design["id"], batch["id"])
    if accept:
        job = accept_quote(customer, job["id"])
    return {"customer": customer, "job": job, "item": item,
            "batch": batch, "design": design}


def setup_packing_job_with_crate(item_overrides: dict | None = None,
                                 batch_overrides: dict | None = None,
                                 customer_overrides: dict | None = None,
                                 pack: bool = False,
                                 indicator_g: int = 75,
                                 moisture_barrier: str = "NONE"):
    """
    Full chain to a crate on a PACKING job: approved design, quote accepted,
    packing started, crate created (design -> LOCKED). When pack=True the crate
    is additionally built and packed. Returns ctx dict with all entities.
    """
    ctx = setup_job_with_approved_design(
        item_overrides=item_overrides, batch_overrides=batch_overrides,
        customer_overrides=customer_overrides, accept=True)
    ctx["job"] = start_packing(ctx["job"]["id"])
    crate = get_success_data(api_client.create_crate(
        ctx["item"]["id"], create_crate_payload(ctx["design"]["id"]), SF))
    ctx["crate"] = crate
    if pack:
        get_success_data(api_client.build_crate(crate["id"], SF))
        crate = get_success_data(api_client.pack_crate(
            crate["id"], pack_crate_payload(indicator_g, moisture_barrier), SF))
        ctx["crate"] = crate
    return ctx


# ─── Tier 3: Full Lifecycle Shortcuts ──────────────────────────────────────

def build_pack_seal_crate(ctx: dict, indicator_g: int = 75,
                          moisture_barrier: str = "NONE"):
    """Drive the ctx crate PLANNED -> BUILT -> PACKED -> SEALED. Returns the SEALED crate."""
    crate = ctx["crate"]
    get_success_data(api_client.build_crate(crate["id"], SF))
    get_success_data(api_client.pack_crate(
        crate["id"], pack_crate_payload(indicator_g, moisture_barrier), SF))
    sealed = get_success_data(api_client.seal_crate(crate["id"], CO))
    ctx["crate"] = sealed
    return sealed


def setup_sealed_crate(item_overrides: dict | None = None,
                       batch_overrides: dict | None = None,
                       customer_overrides: dict | None = None,
                       indicator_g: int = 75, moisture_barrier: str = "NONE"):
    """Job READY_TO_LOAD with one SEALED crate. Returns ctx dict."""
    ctx = setup_packing_job_with_crate(
        item_overrides=item_overrides, batch_overrides=batch_overrides,
        customer_overrides=customer_overrides)
    build_pack_seal_crate(ctx, indicator_g, moisture_barrier)
    ctx["job"] = get_success_data(api_client.get_packing_job(ctx["job"]["id"], SF))
    return ctx


def create_approved_hazmat_declaration(item_id: str, preparer_id: str = "u-foreman-1",
                                       approver_id: str = "u-officer-9", **overrides):
    """Create + submit + approve a declaration with segregated operators.
    Returns the APPROVED HazmatDeclaration."""
    decl = get_success_data(api_client.create_hazmat_declaration(
        item_id, create_hazmat_declaration_payload(**overrides),
        {"X-User-ID": preparer_id, "X-User-Role": "ShopForeman", "Content-Type": "application/json"}))
    get_success_data(api_client.submit_hazmat_declaration(
        decl["id"],
        {"X-User-ID": preparer_id, "X-User-Role": "ShopForeman", "Content-Type": "application/json"}))
    return get_success_data(api_client.approve_hazmat_declaration(
        decl["id"],
        {"X-User-ID": approver_id, "X-User-Role": "ComplianceOfficer", "Content-Type": "application/json"}))


def setup_container_for_crate(ctx: dict, size: str = "40FT", dunnage_weight_kg: float = 0):
    """Create a container and load the ctx SEALED crate into it.
    Returns (container, loaded_crate)."""
    container = get_success_data(api_client.create_container(
        create_container_payload(size=size, dunnage_weight_kg=dunnage_weight_kg), LC))
    loaded = get_success_data(api_client.load_crate(
        container["id"], {"crate_id": ctx["crate"]["id"]}, LC))
    ctx["crate"] = loaded
    ctx["container"] = container
    return container, loaded


def setup_docs_for_job(ctx: dict, unit_price_cents: int, description: str = "Cargo"):
    """Upsert matching packing list + commercial invoice for the job's single
    crate, then finalize and release both. Returns (packing_list, invoice)."""
    crate = ctx["crate"]
    pl = get_success_data(api_client.upsert_packing_list(
        ctx["job"]["id"],
        create_packing_list_payload([packing_list_line(
            crate["id"], description, 1,
            ctx["item"]["weight_kg"], crate["gross_weight_kg"])]), SR))
    ci = get_success_data(api_client.upsert_commercial_invoice(
        ctx["job"]["id"],
        create_commercial_invoice_payload([invoice_line(
            crate["id"], description, 1, unit_price_cents)]), SR))
    get_success_data(api_client.finalize_docs(ctx["job"]["id"], SR))
    get_success_data(api_client.release_docs(ctx["job"]["id"], CO))
    return pl, ci


def setup_shipped_job(item_overrides: dict | None = None,
                      batch_overrides: dict | None = None,
                      customer_overrides: dict | None = None,
                      declared_value_cents: int = 200000):
    """
    Full lifecycle to SHIPPED: sealed crate -> container load/lock/gate-out ->
    docs finalized+released -> ship. The invoice unit price is set to the item's
    declared value so the release-time undervaluation check passes.
    Returns ctx dict (job is SHIPPED).
    """
    item_overrides = dict(item_overrides or {})
    item_overrides.setdefault("declared_value_cents", declared_value_cents)
    ctx = setup_sealed_crate(item_overrides=item_overrides,
                             batch_overrides=batch_overrides,
                             customer_overrides=customer_overrides)
    setup_container_for_crate(ctx)
    get_success_data(api_client.lock_container(ctx["container"]["id"], LC))
    get_success_data(api_client.gate_out_container(ctx["container"]["id"], LC))
    setup_docs_for_job(ctx, unit_price_cents=ctx["item"]["declared_value_cents"],
                       description=ctx["item"]["description"])
    ctx["job"] = get_success_data(api_client.ship_job(ctx["job"]["id"], LC))
    return ctx


def setup_delivered_job(**kwargs):
    """Full lifecycle to DELIVERED (delivered_at stamped from the logical clock).
    Returns ctx dict."""
    ctx = setup_shipped_job(**kwargs)
    ctx["job"] = get_success_data(api_client.deliver_job(ctx["job"]["id"], LC))
    return ctx


# ─── Tier 4: Accumulation / Threshold Targeting ────────────────────────────

def setup_two_packed_crates_one_stamp():
    """
    Two PACKED crates (STANDARD 50x50x50 / 40 kg items) whose designs are both
    approved against a batch holding exactly one stamp — the stamp-quota
    boundary setup. Returns ctx with crate1, crate2, batch.
    """
    customer = create_customer()
    job = create_job(customer)
    item1 = add_item(job["id"], description="Motor A", weight_kg=40)
    item2 = add_item(job["id"], description="Motor B", weight_kg=40)
    batch = create_wood_batch(stamps_acquired=1)
    d1 = get_success_data(api_client.create_design(
        item1["id"], create_design_payload(item1["version"]), CD))
    d1 = submit_and_approve_design(d1["id"], batch["id"])
    d2 = get_success_data(api_client.create_design(
        item2["id"], create_design_payload(item2["version"]), CD))
    d2 = submit_and_approve_design(d2["id"], batch["id"])
    accept_quote(customer, job["id"])
    start_packing(job["id"])
    crate1 = get_success_data(api_client.create_crate(item1["id"], create_crate_payload(d1["id"]), SF))
    crate2 = get_success_data(api_client.create_crate(item2["id"], create_crate_payload(d2["id"]), SF))
    get_success_data(api_client.build_crate(crate1["id"], SF))
    crate1 = get_success_data(api_client.pack_crate(crate1["id"], pack_crate_payload(**STD_PACK), SF))
    get_success_data(api_client.build_crate(crate2["id"], SF))
    crate2 = get_success_data(api_client.pack_crate(crate2["id"], pack_crate_payload(**STD_PACK), SF))
    return {"customer": customer, "job": job, "item1": item1, "item2": item2,
            "batch": batch, "design1": d1, "design2": d2,
            "crate1": crate1, "crate2": crate2}


def setup_two_sealed_dg_crates():
    """
    Two hazmat items (dg_class '1' and '3') with APPROVED declarations under
    segregated operators; both crates SEALED on a shared batch; a PLANNING
    container with crate1 already LOADED. Returns ctx dict.
    """
    customer = create_customer()
    job = create_job(customer)
    item1 = add_item(job["id"], description="Blasting caps", weight_kg=40, hazmat=True)
    item2 = add_item(job["id"], description="Paint drums", weight_kg=40, hazmat=True)
    batch = create_wood_batch()
    d1 = get_success_data(api_client.create_design(
        item1["id"], create_design_payload(item1["version"]), CD))
    d1 = submit_and_approve_design(d1["id"], batch["id"])
    d2 = get_success_data(api_client.create_design(
        item2["id"], create_design_payload(item2["version"]), CD))
    d2 = submit_and_approve_design(d2["id"], batch["id"])
    create_approved_hazmat_declaration(item1["id"], dg_class="1", un_number="UN0333")
    create_approved_hazmat_declaration(item2["id"], dg_class="3", un_number="UN1263")
    accept_quote(customer, job["id"])
    start_packing(job["id"])
    crate1 = get_success_data(api_client.create_crate(item1["id"], create_crate_payload(d1["id"]), SF))
    crate2 = get_success_data(api_client.create_crate(item2["id"], create_crate_payload(d2["id"]), SF))
    for crate in (crate1, crate2):
        get_success_data(api_client.build_crate(crate["id"], SF))
        get_success_data(api_client.pack_crate(crate["id"], pack_crate_payload(**STD_PACK), SF))
        get_success_data(api_client.seal_crate(crate["id"], CO))
    container = get_success_data(api_client.create_container(create_container_payload(), LC))
    get_success_data(api_client.load_crate(container["id"], {"crate_id": crate1["id"]}, LC))
    return {"customer": customer, "job": job, "item1": item1, "item2": item2,
            "batch": batch, "design1": d1, "design2": d2,
            "crate1": crate1, "crate2": crate2, "container": container}


def setup_accepted_job_with_crew(mode: str = "SHOP", capabilities=("SHOP_BUILD",),
                                 item_overrides: dict | None = None):
    """Accepted (DESIGN) job + one item + a crew. Returns (customer, job, item, crew)."""
    customer, job, item = setup_quoted_job_with_item(mode=mode, item_overrides=item_overrides)
    accept_quote(customer, job["id"])
    crew = get_success_data(api_client.create_crew(
        create_crew_payload(capabilities=list(capabilities)), SF))
    return customer, job, item, crew


# ─── Tier 5: Finalization / Terminal State ─────────────────────────────────

def setup_closed_job_with_completed_booking():
    """
    Full lifecycle to CLOSED with one COMPLETED 3.0-hour SHOP booking:
    job DESIGN -> booking RESERVED -> CONFIRMED -> packing -> crate sealed ->
    container gated out -> docs released -> ship -> deliver -> booking
    COMPLETED. Ready for POST /close. Returns ctx dict.
    """
    ctx = setup_job_with_approved_design(
        item_overrides={"description": "Pump assembly", "length_cm": 100, "width_cm": 80,
                        "height_cm": 60, "weight_kg": 40, "declared_value_cents": 500000},
        accept=True)
    crew = get_success_data(api_client.create_crew(create_crew_payload(), SF))
    booking = get_success_data(api_client.create_labor_booking(
        ctx["job"]["id"], create_labor_booking_payload(crew["id"], mode="SHOP"), SF))
    get_success_data(api_client.confirm_labor_booking(booking["id"], SF))
    start_packing(ctx["job"]["id"])
    crate = get_success_data(api_client.create_crate(
        ctx["item"]["id"], create_crate_payload(ctx["design"]["id"]), SF))
    ctx["crate"] = crate
    build_pack_seal_crate(ctx)
    setup_container_for_crate(ctx)
    get_success_data(api_client.lock_container(ctx["container"]["id"], LC))
    get_success_data(api_client.gate_out_container(ctx["container"]["id"], LC))
    setup_docs_for_job(ctx, unit_price_cents=ctx["item"]["declared_value_cents"],
                       description="Pump assembly")
    get_success_data(api_client.ship_job(ctx["job"]["id"], LC))
    get_success_data(api_client.deliver_job(ctx["job"]["id"], LC))
    get_success_data(api_client.complete_labor_booking(booking["id"], SF))
    ctx["crew"] = crew
    ctx["booking"] = booking
    return ctx


def setup_delivered_job_with_reviewed_claims(claim_specs: list,
                                             advance_clock_to: str | None = None):
    """
    Delivered job, then (optionally) advance the logical clock, then file and
    review one claim per spec dict (each spec: claim_type, amount_claimed_cents,
    description). Returns (ctx, [claims]).
    """
    ctx = setup_delivered_job()
    if advance_clock_to:
        get_success_data(api_client.set_logical_clock({"to_iso8601": advance_clock_to}, PA))
    claims = []
    for spec in claim_specs:
        claim = get_success_data(api_client.create_claim(
            ctx["job"]["id"],
            create_claim_payload(ctx["crate"]["id"], **spec),
            make_customer_headers(ctx["customer"]["id"])))
        get_success_data(api_client.review_claim(claim["id"], ADJ))
        claims.append(claim)
    return ctx, claims


def setup_two_jobs_same_customer(site_code: str):
    """One customer (with the given site_code) plus two ONSITE jobs on it.
    Used for permit-window contention tests."""
    customer = create_customer(site_code=site_code)
    job1 = create_job(customer, mode="ONSITE", incoterm="EXW")
    job2 = create_job(customer, mode="ONSITE", incoterm="EXW")
    return customer, job1, job2
