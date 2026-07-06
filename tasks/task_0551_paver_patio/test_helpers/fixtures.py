"""Composite setup helpers.

Each test runs against a freshly launched, empty server, so every fixture
builds its preconditions from scratch using only PRD-declared endpoints.
Setup calls use get_success_data() (lenient) so a broken precondition surfaces
as a clear "Setup failed" rather than a confusing assertion error.
"""
from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .test_users import TEST_USERS, make_client_headers

ADMIN = TEST_USERS["platform_admin_headers"]
DESIGN = TEST_USERS["design_consultant_headers"]
PM = TEST_USERS["project_manager_headers"]


# --------------------------------------------------------------------------
# Low-level builders
# --------------------------------------------------------------------------
def make_customer(api, email="owner@example.com", name="Test Owner"):
    return get_success_data(api.create_customer(f.customer_payload(full_name=name, email=email), DESIGN))


def make_product(api, **overrides):
    return get_success_data(api.create_product(f.product_payload(**overrides), ADMIN))


def make_paver(api, **overrides):
    return get_success_data(api.create_product(f.paver_product_payload(**overrides), ADMIN))


def make_wall_product(api, **overrides):
    return get_success_data(api.create_product(f.wall_product_payload(**overrides), ADMIN))


def make_fire_pit(api, **overrides):
    return get_success_data(api.create_product(f.fire_pit_product_payload(**overrides), ADMIN))


def make_crew(api, name="Test Crew", region="CA"):
    return get_success_data(api.create_crew(f.crew_payload(name=name, region_code=region), ADMIN))


def make_project(api, customer_id, **overrides):
    return get_success_data(api.create_project(f.project_payload(customer_id, **overrides), DESIGN))


def approve_design(api, project_id, customer_id):
    """Create a design revision and drive it DRAFTING -> RENDERED -> IN_REVIEW -> APPROVED."""
    dr = get_success_data(api.create_design_revision(f.design_revision_payload(project_id), DESIGN))
    api.render_design(dr["id"], DESIGN)
    api.submit_review(dr["id"], DESIGN)
    get_success_data(api.approve_design(dr["id"], make_client_headers(customer_id)))
    return dr


def add_measurement(api, project_id, measured_sqft=100, wall_height_in=0, zone="patio"):
    return get_success_data(api.create_site_measurement(
        f.site_measurement_payload(project_id, zone_label=zone,
                                   measured_sqft=measured_sqft, wall_height_in=wall_height_in), DESIGN))


def add_line(api, project_id, product_id, measured_quantity=100):
    return get_success_data(api.create_line_item(
        f.line_item_payload(project_id, product_id, measured_quantity), DESIGN))


def generate_estimate(api, project_id):
    return get_success_data(api.generate_estimate(project_id, DESIGN))


def pay_deposit(api, project_id, amount_cents, expected_version):
    draw = get_success_data(api.create_draw(
        f.draw_payload(project_id, "DEPOSIT", amount_cents, expected_version), PM))
    get_success_data(api.record_payment(draw["id"], PM))
    return draw


def submit_approvals(api, project_id):
    return get_success_data(api.submit_approvals(project_id, PM))


def sign_contract(api, project_id, customer_id):
    return get_success_data(api.sign_contract(project_id, make_client_headers(customer_id)))


# --------------------------------------------------------------------------
# Composite: drive a single-paver-line project to a target posture
# --------------------------------------------------------------------------
def setup_quoted_paver_project(api, measured_sqft=100, wall_height_in=0, in_hoa=False,
                               email="owner@example.com"):
    """Customer + paver product + project driven DRAFT -> QUOTED with one paver line.

    Returns a dict with the customer, product, project (post-estimate), line id and
    the project version observed right after generate-estimate.
    """
    customer = make_customer(api, email=email)
    product = make_paver(api)
    project = make_project(api, customer["id"], in_hoa=in_hoa)
    approve_design(api, project["id"], customer["id"])
    add_measurement(api, project["id"], measured_sqft=measured_sqft, wall_height_in=wall_height_in)
    line = add_line(api, project["id"], product["id"], measured_sqft)
    quoted = generate_estimate(api, project["id"])
    return {
        "customer": customer,
        "product": product,
        "project": quoted,
        "line_id": line["id"],
        "quoted_version": quoted["version"],
    }


def setup_contracted_paver_project(api, measured_sqft=100, wall_height_in=0,
                                   deposit_cents=15000, in_hoa=False, email="owner@example.com"):
    """Extend setup_quoted_paver_project through deposit -> approvals -> sign-contract.

    Returns the same dict plus the signed project and the version observed at signing.
    """
    base = setup_quoted_paver_project(api, measured_sqft=measured_sqft,
                                      wall_height_in=wall_height_in, in_hoa=in_hoa, email=email)
    pid = base["project"]["id"]
    pay_deposit(api, pid, deposit_cents, base["quoted_version"])
    submit_approvals(api, pid)
    signed = sign_contract(api, pid, base["customer"]["id"])
    base["project"] = signed
    base["sign_version"] = signed["version"]
    return base


# --------------------------------------------------------------------------
# Instance-specific fixtures
# --------------------------------------------------------------------------
def setup_dual_variant_completed(api):
    """Big project (paver+wall+fire) driven to COMPLETED with installed 260/40/1.

    Estimate variant uses billable measured quantities; as-built uses installed.
    """
    customer = make_customer(api, email="dv@example.com", name="Dana Vale")
    p_pav = make_paver(api)
    p_wall = make_wall_product(api)
    p_fire = make_fire_pit(api)
    project = make_project(api, customer["id"], in_hoa=False)
    pid = project["id"]
    approve_design(api, pid, customer["id"])
    add_measurement(api, pid, measured_sqft=250, wall_height_in=36, zone="rear patio")
    l1 = add_line(api, pid, p_pav["id"], 250)
    l2 = add_line(api, pid, p_wall["id"], 40)
    l3 = add_line(api, pid, p_fire["id"], 1)
    quoted = generate_estimate(api, pid)
    pay_deposit(api, pid, 75000, quoted["version"])
    submit_approvals(api, pid)
    sign_contract(api, pid, customer["id"])
    mo = get_success_data(api.create_material_order(
        f.material_order_payload(pid, [l1["id"], l2["id"], l3["id"]]), PM))
    api.place_material_order(mo["id"], PM)
    api.confirm_delivery(mo["id"], PM)
    crew = make_crew(api, name="Crew A")
    wp = get_success_data(api.create_work_phase(
        f.work_phase_payload(pid, "FINAL_GRADE",
                             covered_line_item_ids=[l1["id"], l2["id"], l3["id"]], is_final=True), PM))
    api.schedule_work_phase(wp["id"], f.schedule_payload(crew["id"]), PM)
    api.start_production(pid, PM)
    api.start_work_phase(wp["id"], PM)
    completed = get_success_data(api.complete_work_phase(wp["id"], {"installed_quantities": {
        l1["id"]: 260,
        l2["id"]: 40,
        l3["id"]: 1,
    }}, PM))
    project_final = get_success_data(api.get_project(pid, PM))
    return {"project": project_final, "phase": completed, "project_id": pid}


def setup_change_order_ready(api):
    """CONTRACTED project with a single 180-sqft paver line; ready for a change order."""
    base = setup_contracted_paver_project(api, measured_sqft=180, deposit_cents=30000,
                                          email="co@example.com")
    return {
        "project_id": base["project"]["id"],
        "customer": base["customer"],
        "product": base["product"],
        "sign_version": base["sign_version"],
        "project": base["project"],
    }


def setup_permit_boundary_project(api, wall_height_in):
    """DRAFT project with a paver line and one measurement of the given wall height,
    stopped just before generate-estimate."""
    customer = make_customer(api, email="bnd@example.com")
    product = make_paver(api)
    project = make_project(api, customer["id"], in_hoa=False)
    approve_design(api, project["id"], customer["id"])
    add_measurement(api, project["id"], measured_sqft=100, wall_height_in=wall_height_in, zone="seat wall")
    add_line(api, project["id"], product["id"], 100)
    return {"project_id": project["id"], "customer": customer}


def setup_revision_requested_design(api):
    """A design revision taken to IN_REVIEW then sent back (REVISION_REQUESTED)."""
    customer = make_customer(api, email="rl@example.com")
    project = make_project(api, customer["id"])
    dr = get_success_data(api.create_design_revision(f.design_revision_payload(project["id"]), DESIGN))
    api.render_design(dr["id"], DESIGN)
    api.submit_review(dr["id"], DESIGN)
    get_success_data(api.request_revision(dr["id"], make_client_headers(customer["id"])))
    return {"revision_id": dr["id"], "customer": customer}


def setup_hoa_submitted(api, email="ho@example.com"):
    """In-HOA project driven to PENDING_APPROVALS with its HoaSubmission SUBMITTED."""
    customer = make_customer(api, email=email)
    product = make_paver(api)
    project = make_project(api, customer["id"], in_hoa=True)
    pid = project["id"]
    approve_design(api, pid, customer["id"])
    add_measurement(api, pid, measured_sqft=100, wall_height_in=0)
    add_line(api, pid, product["id"], 100)
    generate_estimate(api, pid)
    submit_approvals(api, pid)
    hoa_list, _ = _paginate(api.list_project_hoa_submissions(pid, PM))
    hoa_id = hoa_list[0]["id"]
    get_success_data(api.submit_hoa(hoa_id, PM))
    return {"project_id": pid, "hoa_id": hoa_id, "customer": customer}


def setup_permit_submitted(api):
    """Permit-required project at PENDING_APPROVALS with its Permit SUBMITTED."""
    customer = make_customer(api, email="opd@example.com")
    product = make_paver(api)
    project = make_project(api, customer["id"], in_hoa=False)
    pid = project["id"]
    approve_design(api, pid, customer["id"])
    add_measurement(api, pid, measured_sqft=100, wall_height_in=48, zone="seat wall")
    add_line(api, pid, product["id"], 100)
    generate_estimate(api, pid)
    submit_approvals(api, pid)
    permits, _ = _paginate(api.list_project_permits(pid, PM))
    permit_id = permits[0]["id"]
    get_success_data(api.submit_permit(permit_id, PM))
    return {"project_id": pid, "permit_id": permit_id, "customer": customer}


def setup_wall_build_planned_permit_submitted(api):
    """CONTRACTED permit-required project, Permit SUBMITTED, a fresh crew, and a
    PLANNED WALL_BUILD phase — isolating the permit gate on schedule."""
    base = setup_contracted_paver_project(api, measured_sqft=120, wall_height_in=48,
                                          deposit_cents=20000, email="cx@example.com")
    pid = base["project"]["id"]
    permits, _ = _paginate(api.list_project_permits(pid, PM))
    permit_id = permits[0]["id"]
    api.submit_permit(permit_id, PM)
    crew = make_crew(api, name="Crew E")
    wp = get_success_data(api.create_work_phase(
        f.work_phase_payload(pid, "WALL_BUILD", sequence_index=1), PM))
    return {"project_id": pid, "phase_id": wp["id"], "crew_id": crew["id"], "permit_id": permit_id}


def setup_schedule_safety_conflict(api):
    """CONTRACTED permit-required project, Permit SUBMITTED, a crew already booked
    2026-06-11..2026-06-13, plus a PLANNED WALL_BUILD phase whose schedule overlaps —
    so both the permit gate and the crew-overlap conflict fire."""
    base = setup_contracted_paver_project(api, measured_sqft=120, wall_height_in=48,
                                          deposit_cents=20000, email="sa@example.com")
    pid = base["project"]["id"]
    permits, _ = _paginate(api.list_project_permits(pid, PM))
    permit_id = permits[0]["id"]
    api.submit_permit(permit_id, PM)
    crew = make_crew(api, name="Crew D")
    wp1 = get_success_data(api.create_work_phase(
        f.work_phase_payload(pid, "EXCAVATION", sequence_index=1), PM))
    api.schedule_work_phase(wp1["id"], f.schedule_payload(crew["id"], "2026-06-11", "2026-06-13"), PM)
    wp2 = get_success_data(api.create_work_phase(
        f.work_phase_payload(pid, "WALL_BUILD", sequence_index=2), PM))
    return {"project_id": pid, "phase_id": wp2["id"], "crew_id": crew["id"], "permit_id": permit_id}


def setup_permit_revert_scenario(api):
    """CONTRACTED project (no permit), one SCHEDULED EXCAVATION phase on a crew
    (booking count 1), plus a PROPOSED WALL_BLOCK change order that raises wall to 60in."""
    customer = make_customer(api, email="cc@example.com")
    p_pav = make_paver(api)
    p_wall = make_wall_product(api)
    project = make_project(api, customer["id"], in_hoa=False)
    pid = project["id"]
    approve_design(api, pid, customer["id"])
    add_measurement(api, pid, measured_sqft=180, wall_height_in=0)
    l1 = add_line(api, pid, p_pav["id"], 180)
    quoted = generate_estimate(api, pid)
    pay_deposit(api, pid, 30000, quoted["version"])
    submit_approvals(api, pid)
    signed = sign_contract(api, pid, customer["id"])
    crew = make_crew(api, name="Crew B")
    wp = get_success_data(api.create_work_phase(
        f.work_phase_payload(pid, "EXCAVATION", sequence_index=1), PM))
    api.schedule_work_phase(wp["id"], f.schedule_payload(crew["id"], "2026-06-11", "2026-06-13"), PM)
    co = get_success_data(api.create_change_order(
        f.change_order_payload(pid, p_wall["id"], signed["version"],
                               add_measured_quantity=20, description="add seat wall",
                               add_wall_height_in=60), PM))
    return {"project_id": pid, "phase_id": wp["id"], "crew_id": crew["id"], "change_order_id": co["id"]}


def setup_final_phase_in_progress(api):
    """IN_PRODUCTION project with one is_final phase IN_PROGRESS and one paver line."""
    base = setup_contracted_paver_project(api, measured_sqft=100, deposit_cents=15000,
                                          email="bb@example.com")
    pid = base["project"]["id"]
    line_id = base["line_id"]
    mo = get_success_data(api.create_material_order(f.material_order_payload(pid, [line_id]), PM))
    api.place_material_order(mo["id"], PM)
    api.confirm_delivery(mo["id"], PM)
    crew = make_crew(api, name="Crew C")
    wp = get_success_data(api.create_work_phase(
        f.work_phase_payload(pid, "FINAL_GRADE", covered_line_item_ids=[line_id], is_final=True), PM))
    api.schedule_work_phase(wp["id"], f.schedule_payload(crew["id"]), PM)
    api.start_production(pid, PM)
    api.start_work_phase(wp["id"], PM)
    return {"project_id": pid, "phase_id": wp["id"], "line_id": line_id}


def setup_pallet_material_order(api):
    """CONTRACTED project with two zero-waste paver lines (130, 100 sqft, coverage 120)
    and a DRAFT material order covering both lines."""
    customer = make_customer(api, email="pp@example.com")
    product = make_paver(api, sku="PAV-PLAIN", name="Plain Paver", waste_factor=0,
                         coverage_per_pallet_sqft=120)
    project = make_project(api, customer["id"], in_hoa=False)
    pid = project["id"]
    approve_design(api, pid, customer["id"])
    add_measurement(api, pid, measured_sqft=230, wall_height_in=0)
    l1 = add_line(api, pid, product["id"], 130)
    l2 = add_line(api, pid, product["id"], 100)
    quoted = generate_estimate(api, pid)
    pay_deposit(api, pid, 10000, quoted["version"])
    submit_approvals(api, pid)
    sign_contract(api, pid, customer["id"])
    mo = get_success_data(api.create_material_order(
        f.material_order_payload(pid, [l1["id"], l2["id"]], requested_delivery_date="2026-06-20"), PM))
    return {"project_id": pid, "material_order_id": mo["id"]}


def setup_crew_double_book(api):
    """CONTRACTED project; crew with one SCHEDULED phase over 2026-06-01..2026-06-05
    and a second PLANNED phase awaiting a touching-interval schedule."""
    base = setup_contracted_paver_project(api, measured_sqft=100, deposit_cents=15000,
                                          email="tt@example.com")
    pid = base["project"]["id"]
    crew = make_crew(api, name="Crew F")
    wp1 = get_success_data(api.create_work_phase(
        f.work_phase_payload(pid, "EXCAVATION", sequence_index=1), PM))
    api.schedule_work_phase(wp1["id"], f.schedule_payload(crew["id"], "2026-06-01", "2026-06-05"), PM)
    wp2 = get_success_data(api.create_work_phase(
        f.work_phase_payload(pid, "BASE_PREP", sequence_index=2), PM))
    return {"project_id": pid, "crew_id": crew["id"], "phase_id": wp2["id"]}


def setup_delivery_capacity_full(api):
    """CONTRACTED project with two PLACED material orders for (CA, 2026-06-10) and a
    third DRAFT order for the same region+date."""
    base = setup_contracted_paver_project(api, measured_sqft=100, deposit_cents=15000,
                                          email="cap@example.com")
    pid = base["project"]["id"]
    line_id = base["line_id"]
    mo1 = get_success_data(api.create_material_order(f.material_order_payload(pid, [line_id]), PM))
    api.place_material_order(mo1["id"], PM)
    mo2 = get_success_data(api.create_material_order(f.material_order_payload(pid, [line_id]), PM))
    api.place_material_order(mo2["id"], PM)
    mo3 = get_success_data(api.create_material_order(f.material_order_payload(pid, [line_id]), PM))
    return {"project_id": pid, "material_order_id": mo3["id"]}


def setup_material_order_on_quoted(api):
    """QUOTED project (estimate generated, not signed) with a DRAFT material order."""
    base = setup_quoted_paver_project(api, measured_sqft=100, email="qq@example.com")
    pid = base["project"]["id"]
    mo = get_success_data(api.create_material_order(f.material_order_payload(pid, [base["line_id"]]), PM))
    return {"project_id": pid, "material_order_id": mo["id"]}


def setup_progress_paid_then_ready_to_refund(api):
    """CONTRACTED project with a PAID 15000 deposit and a PAID 20000 PROGRESS draw."""
    base = setup_contracted_paver_project(api, measured_sqft=100, deposit_cents=15000,
                                          email="mm@example.com")
    pid = base["project"]["id"]
    prog = get_success_data(api.create_draw(
        f.draw_payload(pid, "PROGRESS", 20000, base["sign_version"]), PM))
    get_success_data(api.record_payment(prog["id"], PM))
    return {"project_id": pid, "progress_draw_id": prog["id"]}


def setup_scheduled_phase_contracted(api):
    """CONTRACTED project with a crew and one SCHEDULED EXCAVATION phase (booking count 1)."""
    base = setup_contracted_paver_project(api, measured_sqft=100, deposit_cents=15000,
                                          email="cw@example.com")
    pid = base["project"]["id"]
    crew = make_crew(api, name="Crew G")
    wp = get_success_data(api.create_work_phase(
        f.work_phase_payload(pid, "EXCAVATION", sequence_index=1), PM))
    api.schedule_work_phase(wp["id"], f.schedule_payload(crew["id"], "2026-06-11", "2026-06-13"), PM)
    return {"project_id": pid, "crew_id": crew["id"], "phase_id": wp["id"]}


def setup_start_production_no_material(api):
    """CONTRACTED project with a SCHEDULED phase but NO delivered material order —
    isolating the ERR_MATERIAL_NOT_DELIVERED precondition."""
    base = setup_contracted_paver_project(api, measured_sqft=100, deposit_cents=15000,
                                          email="omd@example.com")
    pid = base["project"]["id"]
    crew = make_crew(api, name="Crew MD")
    wp = get_success_data(api.create_work_phase(
        f.work_phase_payload(pid, "EXCAVATION", sequence_index=1), PM))
    api.schedule_work_phase(wp["id"], f.schedule_payload(crew["id"], "2026-06-11", "2026-06-13"), PM)
    return {"project_id": pid, "crew_id": crew["id"], "phase_id": wp["id"]}


def setup_planned_phase_for_date_range(api):
    """CONTRACTED project (no permit), a fresh crew, and a PLANNED EXCAVATION phase."""
    base = setup_contracted_paver_project(api, measured_sqft=100, deposit_cents=15000,
                                          email="odr@example.com")
    pid = base["project"]["id"]
    crew = make_crew(api, name="Crew H")
    wp = get_success_data(api.create_work_phase(
        f.work_phase_payload(pid, "EXCAVATION", sequence_index=1), PM))
    return {"project_id": pid, "crew_id": crew["id"], "phase_id": wp["id"]}


def setup_contracted_owned(api, email="own@example.com"):
    """CONTRACTED project owned by the returned customer (for owner-gated tests)."""
    base = setup_contracted_paver_project(api, measured_sqft=100, deposit_cents=15000, email=email)
    return {"project_id": base["project"]["id"], "customer": base["customer"]}


def setup_pending_approvals_no_deposit(api):
    """PENDING_APPROVALS project (no permit/HOA) with no deposit created."""
    base = setup_quoted_paver_project(api, measured_sqft=100, email="odn@example.com")
    pid = base["project"]["id"]
    submit_approvals(api, pid)
    return {"project_id": pid, "customer": base["customer"]}


def setup_pending_approvals_hoa_unapproved(api):
    """In-HOA PENDING_APPROVALS project, deposit PAID, HoaSubmission still DRAFT."""
    base = setup_quoted_paver_project(api, measured_sqft=100, in_hoa=True, email="ohn@example.com")
    pid = base["project"]["id"]
    pay_deposit(api, pid, 15000, base["quoted_version"])
    submit_approvals(api, pid)
    return {"project_id": pid, "customer": base["customer"]}


def setup_estimate_missing_approved_design(api):
    """Project with a DRAFTING design revision, one measurement, one line (never approved)."""
    customer = make_customer(api, email="ond@example.com")
    product = make_paver(api)
    project = make_project(api, customer["id"])
    dr = get_success_data(api.create_design_revision(f.design_revision_payload(project["id"]), DESIGN))
    add_measurement(api, project["id"], measured_sqft=100, wall_height_in=0)
    add_line(api, project["id"], product["id"], 100)
    return {"project_id": project["id"], "revision_id": dr["id"]}


def setup_estimate_missing_line_items(api):
    """Project with an APPROVED design and one measurement but zero line items."""
    customer = make_customer(api, email="onl@example.com")
    project = make_project(api, customer["id"])
    approve_design(api, project["id"], customer["id"])
    add_measurement(api, project["id"], measured_sqft=100, wall_height_in=0)
    return {"project_id": project["id"]}


def setup_labor_tier_project(api):
    """DRAFT project with a 300-sqft paver line, a 50 face-sqft wall line, and a
    wall measurement of 48in — stopped just before generate-estimate."""
    customer = make_customer(api, email="lb@example.com")
    p_pav = make_paver(api)
    p_wall = make_wall_product(api)
    project = make_project(api, customer["id"], in_hoa=False)
    pid = project["id"]
    approve_design(api, pid, customer["id"])
    add_measurement(api, pid, measured_sqft=300, wall_height_in=48, zone="seat wall")
    add_line(api, pid, p_pav["id"], 300)
    add_line(api, pid, p_wall["id"], 50)
    return {"project_id": pid, "customer": customer}


def setup_prompt_pay_project(api):
    """DRAFT project with a single 3000-sqft paver line (waste 0.10) — large enough
    that the pre-tax subtotal clears the prompt-pay threshold."""
    customer = make_customer(api, email="ppay@example.com")
    product = make_paver(api)
    project = make_project(api, customer["id"], in_hoa=False)
    pid = project["id"]
    approve_design(api, pid, customer["id"])
    add_measurement(api, pid, measured_sqft=3000, wall_height_in=0, zone="driveway")
    add_line(api, pid, product["id"], 3000)
    return {"project_id": pid, "customer": customer}


def setup_stale_change_order(api):
    """CONTRACTED project with one change order already created (project version advanced);
    sign_version is the stale value captured before that first change order."""
    base = setup_contracted_paver_project(api, measured_sqft=180, deposit_cents=30000,
                                          email="ooc@example.com")
    pid = base["project"]["id"]
    product = base["product"]
    get_success_data(api.create_change_order(
        f.change_order_payload(pid, product["id"], base["sign_version"],
                               add_measured_quantity=10, description="first CO"), PM))
    return {"project_id": pid, "product": product, "stale_version": base["sign_version"]}


def setup_stale_draw(api):
    """QUOTED project with one deposit draw already created (project version advanced);
    stale_version is the value captured at generate-estimate."""
    base = setup_quoted_paver_project(api, measured_sqft=100, email="ood@example.com")
    pid = base["project"]["id"]
    get_success_data(api.create_draw(
        f.draw_payload(pid, "DEPOSIT", 5000, base["quoted_version"]), PM))
    return {"project_id": pid, "stale_version": base["quoted_version"]}


# --------------------------------------------------------------------------
# Small internal helper
# --------------------------------------------------------------------------
def _paginate(response):
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(response)
