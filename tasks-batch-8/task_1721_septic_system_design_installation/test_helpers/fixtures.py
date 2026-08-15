"""Composite setup helpers for the septic-ops test suite.

Each helper builds preconditions from scratch using only PRD-declared
endpoints (the server is restarted before every test, so no state carries
over). Setup calls use the lenient get_success_data() validator so a failed
precondition surfaces as a clear "Setup step failed" error.

Identity threading: after a staff record is created, every ownership-gated
call is made with make_<role>_headers(<record id>) — never a shared constant.
"""
from types import SimpleNamespace

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_health_officer_headers,
    make_inspector_headers,
    make_project_manager_headers,
    make_soil_scientist_headers,
    make_system_designer_headers,
)


# ---------------------------------------------------------------------------
# Tier 1/2: company, staff, customer, site
# ---------------------------------------------------------------------------

def setup_company(legal_name="Clearwater Onsite LLC", license_number="CW-100",
                  county_codes=("WH",)) -> SimpleNamespace:
    """Register an installer company. Returns ctx with .cid and .admin."""
    ctx = SimpleNamespace()
    ctx.admin = TEST_USERS["platform_admin_headers"]
    company = get_success_data(api_client.create_installer_company(
        factories.create_installer_company_payload(
            legal_name=legal_name, license_number=license_number,
            county_codes=list(county_codes)),
        ctx.admin))
    ctx.cid = company["id"]
    ctx.company = company
    return ctx


def add_staff(ctx, designer=True, officer=True, manager=True, scientist=True,
              inspector=False, second_inspector=False, second_scientist=False,
              designer_license="DSGN-1", designer_name="Dana Designer",
              officer_badge="HO-1", officer_name="Harriet Officer",
              second_officer_badge=None) -> SimpleNamespace:
    """Register licensed staff on ctx.cid; threads per-entity headers."""
    if designer:
        ctx.d1 = get_success_data(api_client.create_system_designer(
            ctx.cid,
            factories.create_system_designer_payload(
                full_name=designer_name, license_number=designer_license),
            ctx.admin))["id"]
        ctx.designer = make_system_designer_headers(ctx.d1)
    if officer:
        ctx.h1 = get_success_data(api_client.create_health_officer(
            ctx.cid,
            factories.create_health_officer_payload(
                full_name=officer_name, badge_number=officer_badge),
            ctx.admin))["id"]
        ctx.officer = make_health_officer_headers(ctx.h1)
    if second_officer_badge is not None:
        ctx.h2 = get_success_data(api_client.create_health_officer(
            ctx.cid,
            factories.create_health_officer_payload(
                full_name="Harriet Officer", badge_number=second_officer_badge),
            ctx.admin))["id"]
        ctx.officer2 = make_health_officer_headers(ctx.h2)
    if manager:
        ctx.m1 = get_success_data(api_client.create_project_manager(
            ctx.cid, factories.create_project_manager_payload(), ctx.admin))["id"]
        ctx.manager = make_project_manager_headers(ctx.m1)
    if scientist:
        ctx.ss1 = get_success_data(api_client.create_soil_scientist(
            ctx.cid, factories.create_soil_scientist_payload(), ctx.admin))["id"]
        ctx.scientist = make_soil_scientist_headers(ctx.ss1)
    if second_scientist:
        ctx.ss2 = get_success_data(api_client.create_soil_scientist(
            ctx.cid,
            factories.create_soil_scientist_payload(
                full_name="Sue Scientist", license_number="SS-2"),
            ctx.admin))["id"]
        ctx.scientist2 = make_soil_scientist_headers(ctx.ss2)
    if inspector:
        ctx.i1 = get_success_data(api_client.create_inspector(
            ctx.cid, factories.create_inspector_payload(), ctx.admin))["id"]
        ctx.inspector = make_inspector_headers(ctx.i1)
    if second_inspector:
        ctx.i2 = get_success_data(api_client.create_inspector(
            ctx.cid,
            factories.create_inspector_payload(
                full_name="Ivan Inspector", license_number="INS-2"),
            ctx.admin))["id"]
        ctx.inspector2 = make_inspector_headers(ctx.i2)
    return ctx


def setup_company_with_staff(**staff_kwargs) -> SimpleNamespace:
    ctx = setup_company()
    return add_staff(ctx, **staff_kwargs)


def add_customer(ctx, **overrides) -> str:
    ctx.cu = get_success_data(api_client.create_customer(
        ctx.cid, factories.create_customer_payload(**overrides), ctx.manager))["id"]
    return ctx.cu


def add_site(ctx, parcel_id="P-1", address_line="1 Meadow Ln", county_code="WH",
             high_water_table=False, attr="s") -> str:
    """Register a site under ctx.cu; stores id on ctx.<attr>."""
    site_id = get_success_data(api_client.create_site(
        ctx.cid, ctx.cu,
        factories.create_site_payload(
            parcel_id=parcel_id, address_line=address_line,
            county_code=county_code, high_water_table=high_water_table),
        ctx.manager))["id"]
    setattr(ctx, attr, site_id)
    return site_id


def setup_site(high_water_table=False, **staff_kwargs) -> SimpleNamespace:
    """Company + standard staff + customer + one site (ctx.s)."""
    ctx = setup_company_with_staff(**staff_kwargs)
    add_customer(ctx)
    add_site(ctx, high_water_table=high_water_table)
    return ctx


# ---------------------------------------------------------------------------
# Tier 2: science records
# ---------------------------------------------------------------------------

def add_soil_evaluation(ctx, site=None, soil_class="LOAM", limiting_layer_inches=36,
                        attr="e1", evaluator_id=None, scientist_headers=None) -> str:
    sid = site or ctx.s
    eid = get_success_data(api_client.create_soil_evaluation(
        ctx.cid, ctx.cu, sid,
        factories.create_soil_evaluation_payload(
            evaluator_id or ctx.ss1, soil_class=soil_class,
            limiting_layer_inches=limiting_layer_inches),
        scientist_headers or ctx.scientist))["id"]
    setattr(ctx, attr, eid)
    return eid


def add_percolation_test(ctx, site=None, minutes_per_inch=12.0, test_pit_count=4,
                         attr="pt1") -> str:
    sid = site or ctx.s
    ptid = get_success_data(api_client.create_percolation_test(
        ctx.cid, ctx.cu, sid,
        factories.create_percolation_test_payload(
            ctx.ss1, minutes_per_inch=minutes_per_inch, test_pit_count=test_pit_count),
        ctx.scientist))["id"]
    setattr(ctx, attr, ptid)
    return ptid


def add_science(ctx, site=None, soil_class="LOAM", limiting_layer_inches=36,
                minutes_per_inch=12.0, test_pit_count=4, eval_attr="e1",
                perc_attr="pt1") -> tuple:
    eid = add_soil_evaluation(ctx, site=site, soil_class=soil_class,
                              limiting_layer_inches=limiting_layer_inches, attr=eval_attr)
    ptid = add_percolation_test(ctx, site=site, minutes_per_inch=minutes_per_inch,
                                test_pit_count=test_pit_count, attr=perc_attr)
    return eid, ptid


def setup_site_with_science(soil_class="LOAM", limiting_layer_inches=36,
                            high_water_table=False, minutes_per_inch=12.0,
                            test_pit_count=4, **staff_kwargs) -> SimpleNamespace:
    ctx = setup_site(high_water_table=high_water_table, **staff_kwargs)
    add_science(ctx, soil_class=soil_class, limiting_layer_inches=limiting_layer_inches,
                minutes_per_inch=minutes_per_inch, test_pit_count=test_pit_count)
    return ctx


# ---------------------------------------------------------------------------
# Tier 2/3: designs and review actions
# ---------------------------------------------------------------------------

def add_design(ctx, bedroom_count=3, system_type="GRAVITY", supersedes_design_id=None,
               site=None, eval_attr="e1", perc_attr="pt1", attr=None) -> dict:
    """Create a DRAFT design; returns the full design record."""
    sid = site or ctx.s
    payload = factories.create_design_payload(
        ctx.d1, getattr(ctx, eval_attr), getattr(ctx, perc_attr),
        bedroom_count=bedroom_count, system_type=system_type)
    if supersedes_design_id is not None:
        payload["supersedes_design_id"] = supersedes_design_id
    design = get_success_data(api_client.create_design(ctx.cid, ctx.cu, sid, payload, ctx.designer))
    if attr:
        setattr(ctx, attr, design["id"])
    return design


def submit_design(ctx, design_id, site=None) -> dict:
    return get_success_data(api_client.submit_design(
        ctx.cid, ctx.cu, site or ctx.s, design_id, ctx.designer))


def approve_design(ctx, design_id, site=None, officer=None, officer_headers=None) -> dict:
    h_id = officer or ctx.h1
    headers = officer_headers or ctx.officer
    return get_success_data(api_client.decide_design(
        ctx.cid, ctx.cu, site or ctx.s, design_id,
        factories.decide_design_payload(h_id, decision="APPROVE"), headers))


def reject_design(ctx, design_id, site=None,
                  decision_note="Reserve area not staked on plan") -> dict:
    return get_success_data(api_client.decide_design(
        ctx.cid, ctx.cu, site or ctx.s, design_id,
        factories.decide_design_payload(ctx.h1, decision="REJECT", decision_note=decision_note),
        ctx.officer))


def get_design(ctx, design_id, site=None) -> dict:
    return get_success_data(api_client.get_design(
        ctx.cid, ctx.cu, site or ctx.s, design_id, ctx.manager))


def setup_approved_design(bedroom_count=3, system_type="GRAVITY",
                          high_water_table=False, soil_class="LOAM",
                          limiting_layer_inches=36, **staff_kwargs) -> SimpleNamespace:
    """Site + science + design carried through SUBMITTED to APPROVED (ctx.d0)."""
    ctx = setup_site_with_science(
        soil_class=soil_class, limiting_layer_inches=limiting_layer_inches,
        high_water_table=high_water_table, **staff_kwargs)
    design = add_design(ctx, bedroom_count=bedroom_count, system_type=system_type, attr="d0")
    submit_design(ctx, design["id"])
    approve_design(ctx, design["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: permits and installations
# ---------------------------------------------------------------------------

def add_permit(ctx, design_id=None, site=None, attr="p0") -> dict:
    """Issue a permit pinning an APPROVED design; returns the permit record."""
    sid = site or ctx.s
    did = design_id or ctx.d0
    permit = get_success_data(api_client.create_permit(
        ctx.cid, ctx.cu, sid,
        factories.create_permit_payload(did, ctx.h1), ctx.officer))
    setattr(ctx, attr, permit["id"])
    return permit


def get_permit(ctx, permit_id=None, site=None) -> dict:
    return get_success_data(api_client.get_permit(
        ctx.cid, ctx.cu, site or ctx.s, permit_id or ctx.p0, ctx.manager))


def add_installation(ctx, permit_id=None, crew_lead="Carl Crew", site=None, attr="i0") -> dict:
    sid = site or ctx.s
    pid = permit_id or ctx.p0
    installation = get_success_data(api_client.create_installation(
        ctx.cid, ctx.cu, sid,
        factories.create_installation_payload(pid, crew_lead=crew_lead), ctx.manager))
    setattr(ctx, attr, installation["id"])
    return installation


def get_installation(ctx, installation_id=None, site=None) -> dict:
    return get_success_data(api_client.get_installation(
        ctx.cid, ctx.cu, site or ctx.s, installation_id or ctx.i0, ctx.manager))


def setup_installation(bedroom_count=3, system_type="GRAVITY", **kwargs) -> SimpleNamespace:
    """Approved design + permit + NOT_STARTED installation (ctx.d0/p0/i0)."""
    ctx = setup_approved_design(bedroom_count=bedroom_count, system_type=system_type, **kwargs)
    add_permit(ctx)
    add_installation(ctx)
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: installation leg walkers (hold-point gated)
# ---------------------------------------------------------------------------

def advance(ctx, installation_id=None, site=None) -> dict:
    return get_success_data(api_client.advance_installation(
        ctx.cid, ctx.cu, site or ctx.s, installation_id or ctx.i0, ctx.manager))


def deliver_and_verify_material(ctx, installation_id=None, material_kind="TANK",
                                quantity=1, unit_cost_cents=150000, site=None) -> dict:
    sid = site or ctx.s
    iid = installation_id or ctx.i0
    mv = get_success_data(api_client.create_material_verification(
        ctx.cid, ctx.cu, sid, iid,
        factories.create_material_payload(material_kind, quantity, unit_cost_cents),
        ctx.manager))
    return get_success_data(api_client.verify_material(
        ctx.cid, ctx.cu, sid, iid, mv["id"], ctx.manager))


def schedule_inspection(ctx, installation_id=None, hold_point="TANK_SET",
                        scheduled_period=0, inspector_id=None, site=None) -> dict:
    sid = site or ctx.s
    iid = installation_id or ctx.i0
    return get_success_data(api_client.create_inspection(
        ctx.cid, ctx.cu, sid, iid,
        factories.create_inspection_payload(
            inspector_id or ctx.i1, hold_point=hold_point, scheduled_period=scheduled_period),
        ctx.manager))


def pass_inspection(ctx, installation_id, inspection_id, site=None) -> dict:
    sid = site or ctx.s
    return get_success_data(api_client.decide_inspection(
        ctx.cid, ctx.cu, sid, installation_id, inspection_id,
        factories.decide_inspection_payload(decision="PASS"), ctx.inspector))


def pass_hold_point(ctx, installation_id=None, hold_point="TANK_SET",
                    scheduled_period=0, site=None) -> dict:
    insp = schedule_inspection(ctx, installation_id, hold_point, scheduled_period, site=site)
    pass_inspection(ctx, installation_id or ctx.i0, insp["id"], site=site)
    return insp


def walk_installation_to_rough_in(ctx, installation_id=None, site=None) -> dict:
    """NOT_STARTED -> ROUGH_IN_PROGRESS."""
    return advance(ctx, installation_id, site=site)


def walk_installation_to_tank_set(ctx, installation_id=None, site=None,
                                  tank_cost=150000) -> dict:
    """ROUGH_IN_PROGRESS -> TANK_SET (TANK verified + TANK_SET hold passed)."""
    sid = site or ctx.s
    iid = installation_id or ctx.i0
    deliver_and_verify_material(ctx, iid, "TANK", 1, tank_cost, site=sid)
    pass_hold_point(ctx, iid, "TANK_SET", site=sid)
    return advance(ctx, iid, site=sid)


def walk_installation_to_field_installed(ctx, installation_id=None, site=None,
                                         field_material=("PIPE", 50, 500)) -> dict:
    """TANK_SET -> FIELD_INSTALLED (field material verified + FIELD_LAYOUT passed)."""
    sid = site or ctx.s
    iid = installation_id or ctx.i0
    kind, qty, cost = field_material
    deliver_and_verify_material(ctx, iid, kind, qty, cost, site=sid)
    pass_hold_point(ctx, iid, "FIELD_LAYOUT", site=sid)
    return advance(ctx, iid, site=sid)


def walk_installation_to_ready_for_final(ctx, installation_id=None, site=None,
                                         pump_cost=None) -> dict:
    """FIELD_INSTALLED -> READY_FOR_FINAL (verifies a PUMP delivery first when given)."""
    sid = site or ctx.s
    iid = installation_id or ctx.i0
    if pump_cost is not None:
        deliver_and_verify_material(ctx, iid, "PUMP", 1, pump_cost, site=sid)
    return advance(ctx, iid, site=sid)


def complete_installation(ctx, installation_id=None, site=None) -> dict:
    """READY_FOR_FINAL -> COMPLETED via a passed FINAL inspection."""
    sid = site or ctx.s
    iid = installation_id or ctx.i0
    insp = schedule_inspection(ctx, iid, "FINAL", site=sid)
    pass_inspection(ctx, iid, insp["id"], site=sid)
    return get_installation(ctx, iid, site=sid)


def walk_installation_to_completed(ctx, installation_id=None, site=None,
                                   field_material=("PIPE", 50, 500)) -> dict:
    """Full leg chain: NOT_STARTED -> ... -> COMPLETED (GRAVITY-style: no pump)."""
    sid = site or ctx.s
    iid = installation_id or ctx.i0
    walk_installation_to_rough_in(ctx, iid, site=sid)
    walk_installation_to_tank_set(ctx, iid, site=sid)
    walk_installation_to_field_installed(ctx, iid, site=sid, field_material=field_material)
    walk_installation_to_ready_for_final(ctx, iid, site=sid)
    return complete_installation(ctx, iid, site=sid)


def setup_completed_installation(bedroom_count=4, system_type="GRAVITY",
                                 high_water_table=False, soil_class="LOAM",
                                 limiting_layer_inches=36,
                                 field_material=("PIPE", 50, 500)) -> SimpleNamespace:
    """Full happy-path chain ending in a COMPLETED installation (ctx.i0).

    The authorizing permit is FINALIZED as a cascade of completion.
    """
    ctx = setup_installation(
        bedroom_count=bedroom_count, system_type=system_type,
        high_water_table=high_water_table, soil_class=soil_class,
        limiting_layer_inches=limiting_layer_inches, inspector=True)
    walk_installation_to_completed(ctx, field_material=field_material)
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: clock, freeze, and site lifecycle
# ---------------------------------------------------------------------------

def advance_clock(ctx, by_periods=1, site=None) -> dict:
    return get_success_data(api_client.advance_site_clock(
        ctx.cid, ctx.cu, site or ctx.s, factories.advance_clock_payload(by_periods), ctx.manager))


def freeze_site(ctx, freeze_until_period=3, site=None) -> dict:
    return get_success_data(api_client.freeze_site(
        ctx.cid, ctx.cu, site or ctx.s,
        factories.freeze_site_payload(freeze_until_period), ctx.manager))


def get_site(ctx, site=None) -> dict:
    return get_success_data(api_client.get_site(
        ctx.cid, ctx.cu, site or ctx.s, ctx.manager))


# ---------------------------------------------------------------------------
# Tier 4/5: variance requests
# ---------------------------------------------------------------------------

def add_variance_request(ctx, design_id, relief_kind="AREA_REDUCTION",
                         justification="Low-flow fixtures reduce design flow",
                         site=None) -> dict:
    return get_success_data(api_client.create_variance_request(
        ctx.cid, ctx.cu, site or ctx.s,
        factories.create_variance_request_payload(
            design_id, relief_kind=relief_kind, justification=justification),
        ctx.designer))


def approve_variance(ctx, variance_id, site=None, officer=None, officer_headers=None) -> dict:
    h_id = officer or ctx.h1
    headers = officer_headers or ctx.officer
    return get_success_data(api_client.decide_variance_request(
        ctx.cid, ctx.cu, site or ctx.s, variance_id,
        factories.decide_variance_payload(h_id, decision="APPROVE"), headers))


# ---------------------------------------------------------------------------
# Tier 5: maintenance contracts and visits
# ---------------------------------------------------------------------------

def add_maintenance_contract(ctx, installation_id=None, start_period=0, end_period=3,
                             annual_fee_cents=120000, site=None) -> dict:
    return get_success_data(api_client.create_maintenance_contract(
        ctx.cid, ctx.cu, site or ctx.s,
        factories.create_maintenance_contract_payload(
            installation_id or ctx.i0, start_period=start_period,
            end_period=end_period, annual_fee_cents=annual_fee_cents),
        ctx.manager))


def get_contract(ctx, contract_id=None, site=None) -> dict:
    return get_success_data(api_client.get_maintenance_contract(
        ctx.cid, ctx.cu, site or ctx.s, contract_id or ctx.mc, ctx.manager))


def setup_contract(start_period=0, end_period=3, annual_fee_cents=120000,
                   **build_kwargs) -> SimpleNamespace:
    """Completed installation + ACTIVE maintenance contract (ctx.mc)."""
    ctx = setup_completed_installation(**build_kwargs)
    contract = add_maintenance_contract(
        ctx, start_period=start_period, end_period=end_period,
        annual_fee_cents=annual_fee_cents)
    ctx.mc = contract["id"]
    ctx.contract = contract
    return ctx


def setup_lapsed_contract(end_period=3, annual_fee_cents=120000, **build_kwargs) -> SimpleNamespace:
    """Contract whose coverage window the site clock has passed (LAPSED)."""
    ctx = setup_contract(start_period=0, end_period=end_period,
                         annual_fee_cents=annual_fee_cents, **build_kwargs)
    advance_clock(ctx, end_period + 1)
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: repair cases
# ---------------------------------------------------------------------------

def add_repair_case(ctx, failed_installation_id=None, failure_kind="HYDRAULIC_OVERLOAD",
                    diagnosis_note="Field saturated after two wet seasons",
                    site=None, attr="rc") -> dict:
    case = get_success_data(api_client.create_repair_case(
        ctx.cid, ctx.cu, site or ctx.s,
        factories.create_repair_case_payload(
            failed_installation_id or ctx.i0, failure_kind=failure_kind,
            diagnosis_note=diagnosis_note),
        ctx.manager))
    setattr(ctx, attr, case["id"])
    return case


def get_repair_case(ctx, case_id=None, site=None) -> dict:
    return get_success_data(api_client.get_repair_case(
        ctx.cid, ctx.cu, site or ctx.s, case_id or ctx.rc, ctx.manager))


def setup_open_repair_case(**build_kwargs) -> SimpleNamespace:
    """Completed installation + OPEN repair case (ctx.rc)."""
    ctx = setup_completed_installation(**build_kwargs)
    add_repair_case(ctx)
    return ctx
