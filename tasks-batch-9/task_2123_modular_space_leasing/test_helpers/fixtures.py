"""Composite setup helpers.

Every helper drives the API from an empty database using only the endpoints the
PRD declares, and uses the lenient success validator so a broken precondition
surfaces as a clear "Setup step failed" rather than a confusing assertion.

Two standard catalogs recur throughout the suite:

* the **Dallas** catalog — the TX-DAL permitting authority (wind zone 2,
  pier foundations, permit and accessible ramp required) with the 24 x 60
  two-section MOB-2460 model and its 2-Office ADA floorplan; and
* the **Rural** catalog — the TX-RUR authority (wind zone 1, ground anchors,
  neither a permit nor a ramp required) with the 20 x 48 single-section
  MOB-2048 model and its Open Plan floorplan.
"""
from typing import Iterable, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    ACME_CUSTOMER,
    AUSTIN_YARD,
    BASIN_CUSTOMER,
    CONFIG_2_OFFICE_ADA,
    CONFIG_OPEN_PLAN,
    SPEC_MOB_2048,
    SPEC_MOB_2460,
    TX_DAL,
    TX_RUR,
    create_accessory_package_payload,
    create_branch_payload,
    create_building_spec_payload,
    create_customer_payload,
    create_damage_assessment_payload,
    create_damage_line_item_payload,
    create_floorplan_configuration_payload,
    create_jurisdiction_payload,
    create_lease_payload,
    create_logistics_job_payload,
    create_permit_application_payload,
    create_refurbishment_order_payload,
    create_unit_payload,
)
from .test_users import (
    ASSESSOR_ID,
    FLEET_ADMIN_ID,
    SECOND_FLEET_ADMIN_ID,
    make_branch_ops_headers,
    make_customer_headers,
    make_damage_assessor_headers,
    make_fleet_admin_headers,
    make_leasing_agent_headers,
)

# The three damage lines the Dallas chain files, and the single wear line the
# Rural chain files.
DALLAS_DAMAGE_LINES = [
    ("FLOOR", "MODERATE", 1, False),
    ("WALL", "MINOR", 3, True),
    ("HVAC", "SEVERE", 1, False),
]
RURAL_DAMAGE_LINES = [("HVAC", "MODERATE", 1, True)]


# ─── Tier 0: single-call wrappers ────────────────────────────────────────────

def set_clock(to_iso8601: str) -> dict:
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, make_fleet_admin_headers()))


def create_branch(**overrides) -> dict:
    return get_success_data(
        api_client.create_branch(create_branch_payload(**overrides),
                                 make_fleet_admin_headers()))


def create_jurisdiction(**overrides) -> dict:
    return get_success_data(
        api_client.create_jurisdiction(create_jurisdiction_payload(**overrides),
                                       make_fleet_admin_headers()))


def create_building_spec(**overrides) -> dict:
    return get_success_data(
        api_client.create_building_spec(create_building_spec_payload(**overrides),
                                        make_fleet_admin_headers()))


def create_configuration(building_spec_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_floorplan_configuration(
            create_floorplan_configuration_payload(building_spec_id, **overrides),
            make_fleet_admin_headers()))


def publish_configuration(config_id: str) -> dict:
    return get_success_data(
        api_client.publish_floorplan_configuration(
            config_id, make_fleet_admin_headers()))


def create_published_configuration(building_spec_id: str, **overrides) -> dict:
    config = create_configuration(building_spec_id, **overrides)
    return publish_configuration(config["id"])


def create_unit(building_spec_id: str, current_branch_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_unit(
            create_unit_payload(building_spec_id, current_branch_id, **overrides),
            make_fleet_admin_headers()))


def create_customer(**overrides) -> dict:
    return get_success_data(
        api_client.create_customer(create_customer_payload(**overrides),
                                   make_leasing_agent_headers()))


def create_lease(customer_id: str, unit_id: str, jurisdiction_id: str,
                 config_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_lease(
            create_lease_payload(customer_id, unit_id, jurisdiction_id, config_id,
                                 **overrides),
            make_leasing_agent_headers()))


def attach_accessory_package(lease_id: str, package_type: str = "STEPS",
                             **overrides) -> dict:
    return get_success_data(
        api_client.create_accessory_package(
            create_accessory_package_payload(lease_id, package_type, **overrides),
            make_leasing_agent_headers()))


def create_permit(lease_id: str, jurisdiction_id: str, foundation_type: str) -> dict:
    return get_success_data(
        api_client.create_permit_application(
            create_permit_application_payload(lease_id, jurisdiction_id,
                                              foundation_type),
            make_leasing_agent_headers()))


def submit_permit(permit_id: str) -> dict:
    return get_success_data(
        api_client.submit_permit_application(permit_id, make_leasing_agent_headers()))


def decide_permit(permit_id: str, decision: str, reviewer_note: Optional[str] = None
                  ) -> dict:
    payload = {"decision": decision}
    if reviewer_note is not None:
        payload["reviewer_note"] = reviewer_note
    return get_success_data(
        api_client.decide_permit_application(permit_id, payload,
                                             make_fleet_admin_headers()))


def approve_permit_for_lease(lease_id: str, jurisdiction_id: str,
                             foundation_type: str = "PIER_FOUNDATION") -> dict:
    """Draft, file and approve a permit in one step. Returns the APPROVED row."""
    permit = create_permit(lease_id, jurisdiction_id, foundation_type)
    submit_permit(permit["id"])
    return decide_permit(permit["id"], "APPROVED")


def activate_lease(lease_id: str) -> dict:
    return get_success_data(
        api_client.activate_lease(lease_id, make_leasing_agent_headers()))


def void_lease(lease_id: str, void_reason: Optional[str] = None) -> dict:
    payload = {"void_reason": void_reason} if void_reason else {}
    return get_success_data(
        api_client.void_lease(lease_id, make_leasing_agent_headers(), payload))


def extend_lease(lease_id: str, term_months: int) -> dict:
    return get_success_data(
        api_client.extend_lease(lease_id, {"term_months": term_months},
                                make_leasing_agent_headers()))


def book_job(lease_id: str, origin_branch_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_logistics_job(
            create_logistics_job_payload(lease_id, origin_branch_id, **overrides),
            make_branch_ops_headers(origin_branch_id)))


def dispatch_job(job_id: str, origin_branch_id: str) -> dict:
    return get_success_data(
        api_client.dispatch_logistics_job(
            job_id, make_branch_ops_headers(origin_branch_id)))


def complete_job(job_id: str, origin_branch_id: str) -> dict:
    return get_success_data(
        api_client.complete_logistics_job(
            job_id, make_branch_ops_headers(origin_branch_id)))


def cancel_job(job_id: str, origin_branch_id: str,
               cancellation_reason: Optional[str] = None) -> dict:
    payload = {"cancellation_reason": cancellation_reason} if cancellation_reason else {}
    return get_success_data(
        api_client.cancel_logistics_job(
            job_id, make_branch_ops_headers(origin_branch_id), payload))


def open_assessment(lease_id: str, unit_id: str, logistics_job_id: str,
                    expected_lease_version: Optional[int] = None,
                    assessor_id: str = ASSESSOR_ID) -> dict:
    if expected_lease_version is None:
        expected_lease_version = get_lease(lease_id)["version"]
    return get_success_data(
        api_client.create_damage_assessment(
            create_damage_assessment_payload(lease_id, unit_id, logistics_job_id,
                                             expected_lease_version),
            make_damage_assessor_headers(assessor_id)))


def add_line_item(assessment_id: str, component: str, severity: str,
                  quantity: float, wear_and_tear: bool,
                  assessor_id: str = ASSESSOR_ID) -> dict:
    return get_success_data(
        api_client.create_damage_line_item(
            assessment_id,
            create_damage_line_item_payload(component, severity, quantity,
                                            wear_and_tear),
            make_damage_assessor_headers(assessor_id)))


def add_line_items(assessment_id: str, lines: Iterable, assessor_id: str = ASSESSOR_ID
                   ) -> List[dict]:
    return [add_line_item(assessment_id, *line, assessor_id=assessor_id)
            for line in lines]


def submit_assessment(assessment_id: str, assessor_id: str = ASSESSOR_ID) -> dict:
    return get_success_data(
        api_client.submit_damage_assessment(
            assessment_id, make_damage_assessor_headers(assessor_id)))


def dispute_assessment(assessment_id: str, customer_id: str,
                       dispute_reason: str = "Disputed at teardown") -> dict:
    return get_success_data(
        api_client.dispute_damage_assessment(
            assessment_id, {"dispute_reason": dispute_reason},
            make_customer_headers(customer_id)))


def finalize_assessment(assessment_id: str, condition_grade_after: str = "B",
                        admin_id: str = FLEET_ADMIN_ID) -> dict:
    return get_success_data(
        api_client.finalize_damage_assessment(
            assessment_id, {"condition_grade_after": condition_grade_after},
            make_fleet_admin_headers(admin_id)))


def quote_refurbishment(unit_id: str, branch_id: str, assessment_id: str,
                        expected_unit_version: Optional[int] = None,
                        **overrides) -> dict:
    if expected_unit_version is None:
        expected_unit_version = get_unit(unit_id)["version"]
    return get_success_data(
        api_client.create_refurbishment_order(
            create_refurbishment_order_payload(unit_id, branch_id, assessment_id,
                                               expected_unit_version, **overrides),
            make_branch_ops_headers(branch_id)))


def approve_refurbishment(order_id: str, admin_id: str = SECOND_FLEET_ADMIN_ID) -> dict:
    return get_success_data(
        api_client.approve_refurbishment_order(
            order_id, make_fleet_admin_headers(admin_id)))


def reject_refurbishment(order_id: str, rejection_reason: str = "Leasable as-is",
                         admin_id: str = SECOND_FLEET_ADMIN_ID) -> dict:
    return get_success_data(
        api_client.reject_refurbishment_order(
            order_id, {"rejection_reason": rejection_reason},
            make_fleet_admin_headers(admin_id)))


def complete_refurbishment(order_id: str, branch_id: str,
                           actual_cost_cents: int) -> dict:
    return get_success_data(
        api_client.complete_refurbishment_order(
            order_id, {"actual_cost_cents": actual_cost_cents},
            make_branch_ops_headers(branch_id)))


# ─── Readers ─────────────────────────────────────────────────────────────────

def get_branch(branch_id: str) -> dict:
    return get_success_data(
        api_client.get_branch(branch_id, make_fleet_admin_headers()))


def get_building_spec(spec_id: str) -> dict:
    return get_success_data(
        api_client.get_building_spec(spec_id, make_fleet_admin_headers()))


def get_configuration(config_id: str) -> dict:
    return get_success_data(
        api_client.get_floorplan_configuration(config_id, make_fleet_admin_headers()))


def get_unit(unit_id: str) -> dict:
    return get_success_data(
        api_client.get_unit(unit_id, make_fleet_admin_headers()))


def get_customer(customer_id: str) -> dict:
    return get_success_data(
        api_client.get_customer(customer_id, make_leasing_agent_headers()))


def get_lease(lease_id: str) -> dict:
    return get_success_data(
        api_client.get_lease(lease_id, make_leasing_agent_headers()))


def get_accessory_package(package_id: str) -> dict:
    return get_success_data(
        api_client.get_accessory_package(package_id, make_leasing_agent_headers()))


def get_permit(permit_id: str) -> dict:
    return get_success_data(
        api_client.get_permit_application(permit_id, make_leasing_agent_headers()))


def get_job(job_id: str) -> dict:
    return get_success_data(
        api_client.get_logistics_job(job_id, make_fleet_admin_headers()))


def get_assessment(assessment_id: str) -> dict:
    return get_success_data(
        api_client.get_damage_assessment(assessment_id, make_fleet_admin_headers()))


def get_refurbishment_order(order_id: str) -> dict:
    return get_success_data(
        api_client.get_refurbishment_order(order_id, make_fleet_admin_headers()))


# ─── Tier 1: catalogs ────────────────────────────────────────────────────────

def setup_rural_catalog(unit_count: int = 1, branch_overrides: Optional[dict] = None,
                        customer_overrides: Optional[dict] = None,
                        publish: bool = True) -> dict:
    """Dallas Yard + the permit-free TX-RUR authority + the MOB-2048 model with
    its Open Plan floorplan + `unit_count` IN_FLEET units + one GOLD lessee."""
    branch = create_branch(**(branch_overrides or {}))
    jurisdiction = create_jurisdiction(**TX_RUR)
    spec = create_building_spec(**SPEC_MOB_2048)
    if publish:
        config = create_published_configuration(spec["id"], **CONFIG_OPEN_PLAN)
    else:
        config = create_configuration(spec["id"], **CONFIG_OPEN_PLAN)
    units = [
        create_unit(spec["id"], branch["id"], serial_number=f"MSU-200{i + 1}")
        for i in range(unit_count)
    ]
    customer = create_customer(**{**BASIN_CUSTOMER, **(customer_overrides or {})})
    return {
        "branch": branch,
        "jurisdiction": jurisdiction,
        "spec": spec,
        "config": config,
        "unit": units[0] if units else None,
        "units": units,
        "customer": customer,
    }


def setup_dallas_catalog(unit_count: int = 1, branch_overrides: Optional[dict] = None,
                         customer_overrides: Optional[dict] = None) -> dict:
    """Dallas Yard + the TX-DAL authority (permit and ramp required) + the
    MOB-2460 model with its 2-Office ADA floorplan + `unit_count` IN_FLEET
    units + one GOLD lessee."""
    branch = create_branch(**(branch_overrides or {}))
    jurisdiction = create_jurisdiction(**TX_DAL)
    spec = create_building_spec(**SPEC_MOB_2460)
    config = create_published_configuration(spec["id"], **CONFIG_2_OFFICE_ADA)
    units = [
        create_unit(spec["id"], branch["id"], serial_number=f"MSU-100{i + 1}")
        for i in range(unit_count)
    ]
    customer = create_customer(**{**ACME_CUSTOMER, **(customer_overrides or {})})
    return {
        "branch": branch,
        "jurisdiction": jurisdiction,
        "spec": spec,
        "config": config,
        "unit": units[0] if units else None,
        "units": units,
        "customer": customer,
    }


def add_austin_branch(ctx: dict, **overrides) -> dict:
    """Add a second yard to an existing catalog context."""
    branch = create_branch(**{**AUSTIN_YARD, **overrides})
    ctx["austin_branch"] = branch
    return branch


# ─── Tier 2: leases ──────────────────────────────────────────────────────────

RURAL_SITE = "9 County Road 12, Rural TX"
DALLAS_SITE = "400 Commerce St, Dallas TX"


def setup_rural_lease(term_months: int = 12, start_date: str = "2026-10-01",
                      site_address: str = RURAL_SITE, ctx: Optional[dict] = None,
                      **catalog_kwargs) -> dict:
    """Rural catalog + one PENDING / UNBILLED lease on its first unit."""
    ctx = ctx or setup_rural_catalog(**catalog_kwargs)
    ctx["lease"] = create_lease(
        ctx["customer"]["id"], ctx["unit"]["id"], ctx["jurisdiction"]["id"],
        ctx["config"]["id"], site_address=site_address, start_date=start_date,
        term_months=term_months)
    return ctx


def setup_dallas_lease(term_months: int = 12, start_date: str = "2026-09-01",
                       site_address: str = DALLAS_SITE, with_package: bool = True,
                       ctx: Optional[dict] = None, **catalog_kwargs) -> dict:
    """Dallas catalog + one PENDING / UNBILLED lease, optionally already
    carrying the COMPLIANT COMBO steps-and-ramp package."""
    ctx = ctx or setup_dallas_catalog(**catalog_kwargs)
    ctx["lease"] = create_lease(
        ctx["customer"]["id"], ctx["unit"]["id"], ctx["jurisdiction"]["id"],
        ctx["config"]["id"], site_address=site_address, start_date=start_date,
        term_months=term_months)
    if with_package:
        ctx["package"] = attach_accessory_package(
            ctx["lease"]["id"], "COMBO", ramp_run_ft=36.0, landing_count=2,
            step_count=4)
    return ctx


# ─── Tier 3: installed and vacated lifecycles ────────────────────────────────

def setup_rural_installed_lease(scheduled_date: str = "2026-10-01",
                                mileage_miles: float = 40,
                                crew_hours: float = 4.0,
                                ctx: Optional[dict] = None,
                                **lease_kwargs) -> dict:
    """Activate the rural lease and run its delivery-and-install job right
    through to completion, leaving the lease INSTALLED / ACCRUING and the unit
    ON_LEASE."""
    ctx = ctx or setup_rural_lease(**lease_kwargs)
    activate_lease(ctx["lease"]["id"])
    job = book_job(ctx["lease"]["id"], ctx["branch"]["id"],
                   job_type="DELIVERY_INSTALL", scheduled_date=scheduled_date,
                   mileage_miles=mileage_miles, crew_hours=crew_hours)
    dispatch_job(job["id"], ctx["branch"]["id"])
    ctx["delivery_job"] = complete_job(job["id"], ctx["branch"]["id"])
    ctx["lease"] = get_lease(ctx["lease"]["id"])
    return ctx


def setup_dallas_installed_lease(scheduled_date: str = "2026-09-01",
                                 mileage_miles: float = 180,
                                 crew_hours: float = 6.5,
                                 ctx: Optional[dict] = None,
                                 **lease_kwargs) -> dict:
    """Approve the TX-DAL permit, activate the lease and run the
    delivery-and-install job through to completion."""
    ctx = ctx or setup_dallas_lease(**lease_kwargs)
    ctx["permit"] = approve_permit_for_lease(
        ctx["lease"]["id"], ctx["jurisdiction"]["id"], "PIER_FOUNDATION")
    activate_lease(ctx["lease"]["id"])
    job = book_job(ctx["lease"]["id"], ctx["branch"]["id"],
                   job_type="DELIVERY_INSTALL", scheduled_date=scheduled_date,
                   mileage_miles=mileage_miles, crew_hours=crew_hours)
    dispatch_job(job["id"], ctx["branch"]["id"])
    ctx["delivery_job"] = complete_job(job["id"], ctx["branch"]["id"])
    ctx["lease"] = get_lease(ctx["lease"]["id"])
    return ctx


def setup_rural_vacated_lease(vacate_date: str = "2026-10-20",
                              mileage_miles: float = 40,
                              crew_hours: float = 4.0,
                              teardown_branch_id: Optional[str] = None,
                              destination_branch_id: Optional[str] = None,
                              ctx: Optional[dict] = None,
                              **installed_kwargs) -> dict:
    """Move the clock to `vacate_date` and run the teardown-and-return job to
    completion, leaving the lease VACATED / ACCRUING and the unit RETURNED."""
    ctx = ctx or setup_rural_installed_lease(**installed_kwargs)
    origin = teardown_branch_id or ctx["branch"]["id"]
    destination = destination_branch_id or origin
    set_clock(f"{vacate_date}T00:00:00Z")
    job = book_job(ctx["lease"]["id"], origin, job_type="TEARDOWN_RETURN",
                   scheduled_date=vacate_date, mileage_miles=mileage_miles,
                   crew_hours=crew_hours, destination_branch_id=destination)
    dispatch_job(job["id"], origin)
    ctx["teardown_job"] = complete_job(job["id"], origin)
    ctx["lease"] = get_lease(ctx["lease"]["id"])
    ctx["unit"] = get_unit(ctx["unit"]["id"])
    return ctx


def setup_dallas_vacated_lease(vacate_date: str = "2027-06-15",
                               mileage_miles: float = 180,
                               crew_hours: float = 5.0,
                               teardown_branch_id: Optional[str] = None,
                               destination_branch_id: Optional[str] = None,
                               ctx: Optional[dict] = None,
                               **installed_kwargs) -> dict:
    ctx = ctx or setup_dallas_installed_lease(**installed_kwargs)
    origin = teardown_branch_id or ctx["branch"]["id"]
    destination = destination_branch_id or origin
    set_clock(f"{vacate_date}T00:00:00Z")
    job = book_job(ctx["lease"]["id"], origin, job_type="TEARDOWN_RETURN",
                   scheduled_date=vacate_date, mileage_miles=mileage_miles,
                   crew_hours=crew_hours, destination_branch_id=destination)
    dispatch_job(job["id"], origin)
    ctx["teardown_job"] = complete_job(job["id"], origin)
    ctx["lease"] = get_lease(ctx["lease"]["id"])
    ctx["unit"] = get_unit(ctx["unit"]["id"])
    return ctx


def setup_dispatched_teardown(vacate_date: str = "2026-10-20",
                              mileage_miles: float = 40,
                              crew_hours: float = 4.0,
                              teardown_branch_id: Optional[str] = None,
                              destination_branch_id: Optional[str] = None,
                              ctx: Optional[dict] = None,
                              **installed_kwargs) -> dict:
    """Rural chain stopped one step short of vacating: the teardown job is
    DISPATCHED but not yet completed."""
    ctx = ctx or setup_rural_installed_lease(**installed_kwargs)
    origin = teardown_branch_id or ctx["branch"]["id"]
    destination = destination_branch_id or origin
    set_clock(f"{vacate_date}T00:00:00Z")
    job = book_job(ctx["lease"]["id"], origin, job_type="TEARDOWN_RETURN",
                   scheduled_date=vacate_date, mileage_miles=mileage_miles,
                   crew_hours=crew_hours, destination_branch_id=destination)
    ctx["teardown_job"] = dispatch_job(job["id"], origin)
    ctx["teardown_origin_branch_id"] = origin
    return ctx


# ─── Tier 4: damage assessments ──────────────────────────────────────────────

def setup_rural_draft_assessment(lines: Optional[Iterable] = None,
                                 assessor_id: str = ASSESSOR_ID,
                                 ctx: Optional[dict] = None,
                                 **vacated_kwargs) -> dict:
    """Rural chain vacated, with a DRAFT assessment carrying `lines`."""
    ctx = ctx or setup_rural_vacated_lease(**vacated_kwargs)
    assessment = open_assessment(ctx["lease"]["id"], ctx["unit"]["id"],
                                 ctx["teardown_job"]["id"], assessor_id=assessor_id)
    ctx["line_items"] = add_line_items(
        assessment["id"],
        RURAL_DAMAGE_LINES if lines is None else lines,
        assessor_id=assessor_id)
    ctx["assessment"] = get_assessment(assessment["id"])
    return ctx


def setup_rural_submitted_assessment(lines: Optional[Iterable] = None,
                                     assessor_id: str = ASSESSOR_ID,
                                     ctx: Optional[dict] = None,
                                     **vacated_kwargs) -> dict:
    ctx = ctx or setup_rural_draft_assessment(lines=lines, assessor_id=assessor_id,
                                              **vacated_kwargs)
    ctx["assessment"] = submit_assessment(ctx["assessment"]["id"],
                                          assessor_id=assessor_id)
    return ctx


def setup_rural_finalized_assessment(condition_grade_after: str = "B",
                                     lines: Optional[Iterable] = None,
                                     assessor_id: str = ASSESSOR_ID,
                                     admin_id: str = FLEET_ADMIN_ID,
                                     ctx: Optional[dict] = None,
                                     **vacated_kwargs) -> dict:
    ctx = ctx or setup_rural_submitted_assessment(lines=lines, assessor_id=assessor_id,
                                                  **vacated_kwargs)
    ctx["assessment"] = finalize_assessment(ctx["assessment"]["id"],
                                            condition_grade_after, admin_id=admin_id)
    ctx["lease"] = get_lease(ctx["lease"]["id"])
    ctx["customer"] = get_customer(ctx["customer"]["id"])
    ctx["unit"] = get_unit(ctx["unit"]["id"])
    return ctx


def setup_dallas_draft_assessment(lines: Optional[Iterable] = None,
                                  assessor_id: str = ASSESSOR_ID,
                                  ctx: Optional[dict] = None,
                                  **vacated_kwargs) -> dict:
    ctx = ctx or setup_dallas_vacated_lease(**vacated_kwargs)
    assessment = open_assessment(ctx["lease"]["id"], ctx["unit"]["id"],
                                 ctx["teardown_job"]["id"], assessor_id=assessor_id)
    ctx["line_items"] = add_line_items(
        assessment["id"],
        DALLAS_DAMAGE_LINES if lines is None else lines,
        assessor_id=assessor_id)
    ctx["assessment"] = get_assessment(assessment["id"])
    return ctx


def setup_dallas_submitted_assessment(lines: Optional[Iterable] = None,
                                      assessor_id: str = ASSESSOR_ID,
                                      ctx: Optional[dict] = None,
                                      **vacated_kwargs) -> dict:
    ctx = ctx or setup_dallas_draft_assessment(lines=lines, assessor_id=assessor_id,
                                               **vacated_kwargs)
    ctx["assessment"] = submit_assessment(ctx["assessment"]["id"],
                                          assessor_id=assessor_id)
    return ctx


def setup_dallas_finalized_assessment(condition_grade_after: str = "C",
                                      lines: Optional[Iterable] = None,
                                      assessor_id: str = ASSESSOR_ID,
                                      admin_id: str = FLEET_ADMIN_ID,
                                      ctx: Optional[dict] = None,
                                      **vacated_kwargs) -> dict:
    ctx = ctx or setup_dallas_submitted_assessment(lines=lines, assessor_id=assessor_id,
                                                   **vacated_kwargs)
    ctx["assessment"] = finalize_assessment(ctx["assessment"]["id"],
                                            condition_grade_after, admin_id=admin_id)
    ctx["lease"] = get_lease(ctx["lease"]["id"])
    ctx["customer"] = get_customer(ctx["customer"]["id"])
    ctx["unit"] = get_unit(ctx["unit"]["id"])
    return ctx


# ─── Tier 5: refurbishment ───────────────────────────────────────────────────

def setup_rural_quoted_refurbishment(scope: str = "COSMETIC",
                                     labor_hours: float = 12.5,
                                     parts_cost_cents: int = 143_719,
                                     target_condition_grade: str = "B",
                                     ctx: Optional[dict] = None,
                                     **finalized_kwargs) -> dict:
    """Rural chain with the unit RETURNED and one QUOTED refurbishment order."""
    ctx = ctx or setup_rural_finalized_assessment(**finalized_kwargs)
    ctx["order"] = quote_refurbishment(
        ctx["unit"]["id"], ctx["branch"]["id"], ctx["assessment"]["id"],
        scope=scope, labor_hours=labor_hours, parts_cost_cents=parts_cost_cents,
        target_condition_grade=target_condition_grade)
    ctx["unit"] = get_unit(ctx["unit"]["id"])
    return ctx


def setup_dallas_quoted_refurbishment(scope: str = "STANDARD",
                                      labor_hours: float = 12.5,
                                      parts_cost_cents: int = 143_700,
                                      target_condition_grade: str = "B",
                                      ctx: Optional[dict] = None,
                                      **finalized_kwargs) -> dict:
    ctx = ctx or setup_dallas_finalized_assessment(**finalized_kwargs)
    ctx["order"] = quote_refurbishment(
        ctx["unit"]["id"], ctx["branch"]["id"], ctx["assessment"]["id"],
        scope=scope, labor_hours=labor_hours, parts_cost_cents=parts_cost_cents,
        target_condition_grade=target_condition_grade)
    ctx["unit"] = get_unit(ctx["unit"]["id"])
    return ctx


def setup_rural_refurbishing_unit(admin_id: str = SECOND_FLEET_ADMIN_ID,
                                  ctx: Optional[dict] = None,
                                  **quote_kwargs) -> dict:
    """Rural chain with the refurbishment approved, so the unit is REFURBISHING."""
    ctx = ctx or setup_rural_quoted_refurbishment(**quote_kwargs)
    ctx["order"] = approve_refurbishment(ctx["order"]["id"], admin_id=admin_id)
    ctx["unit"] = get_unit(ctx["unit"]["id"])
    return ctx
