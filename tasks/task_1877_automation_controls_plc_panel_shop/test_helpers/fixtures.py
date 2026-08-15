"""Composite setup helpers.

Every fixture builds preconditions from scratch via PRD-declared endpoints
(each test starts against an empty database). All setup calls use the lenient
get_success_data() validator so failures surface as clear "Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_change_order_payload,
    create_component_payload,
    create_customer_payload,
    create_job_payload,
    create_panel_component_payload,
    create_panel_payload,
    create_program_version_payload,
    create_startup_session_payload,
    create_substitution_request_payload,
    create_test_point_payload,
    create_test_session_payload,
    create_warranty_claim_payload,
    unique_content_hash,
)
from .test_users import (
    TEST_USERS,
    make_customer_headers,
    make_designer_headers,
    make_field_engineer_headers,
    make_qa_headers,
    make_technician_headers,
)

PM = TEST_USERS["project_manager_headers"]
QA = TEST_USERS["qa_manager_headers"]
DE = TEST_USERS["design_engineer_headers"]
SL = TEST_USERS["shop_lead_headers"]
TT = TEST_USERS["test_technician_headers"]
CE = TEST_USERS["controls_engineer_headers"]
FE = TEST_USERS["field_engineer_headers"]
SHIPPING = TEST_USERS["shipping_clerk_headers"]

# A 100 kA current-limiting branch-protective device: clears the 5 kA review
# floor on its own and exercises the conditional-raise branch (PRD §3.2).
DEFAULT_COMPONENT = {
    "part_number": "BPD-FX100",
    "component_class": "BRANCH_PROTECTIVE",
    "unit_cost_cents": 45000,
    "lead_time_days": 21,
    "sccr_ka": 100,
    "heat_dissipation_w": 12,
}

DEFAULT_SESSION_START = "2026-10-01T08:00:00Z"
DEFAULT_SESSION_END = "2026-10-01T18:00:00Z"
DEFAULT_WORK_TIME = "2026-10-01T09:00:00Z"


# ---------------------------------------------------------------------------
# Tier 1: single-entity creators
# ---------------------------------------------------------------------------

def new_customer(**overrides) -> dict:
    resp = api_client.create_customer(create_customer_payload(**overrides), PM)
    return get_success_data(resp, 201)


def new_job(customer_id: str, **overrides) -> dict:
    resp = api_client.create_job(create_job_payload(customer_id, **overrides), PM)
    return get_success_data(resp, 201)


def new_panel(job_id: str, design_engineer_id: str = "de-100", **overrides) -> dict:
    payload = create_panel_payload(design_engineer_id=design_engineer_id, **overrides)
    resp = api_client.create_panel(job_id, payload, DE)
    return get_success_data(resp, 201)


def new_component(**overrides) -> dict:
    resp = api_client.create_component(create_component_payload(**overrides), QA)
    return get_success_data(resp, 201)


def add_bom_line(panel_id: str, component_id: str, quantity: int = 1) -> dict:
    resp = api_client.add_panel_component(
        panel_id, create_panel_component_payload(component_id, quantity=quantity), DE
    )
    return get_success_data(resp, 201)


def new_test_point(panel_id: str, **overrides) -> dict:
    resp = api_client.create_test_point(panel_id, create_test_point_payload(**overrides), DE)
    return get_success_data(resp, 201)


def new_change_order(job_id: str, **overrides) -> dict:
    resp = api_client.create_change_order(job_id, create_change_order_payload(**overrides), PM)
    return get_success_data(resp, 201)


def set_clock(to_iso8601: str):
    get_success_data(api_client.set_clock(to_iso8601, PM), 200)


# ---------------------------------------------------------------------------
# Tier 2/3: panel lifecycle walkers
# ---------------------------------------------------------------------------

def walk_panel_to_design_approved(panel_id: str, qa_user_id: str = "qa-100") -> dict:
    """DESIGN -> DESIGN_REVIEW -> DESIGN_APPROVED (QA differs from designer)."""
    get_success_data(api_client.submit_review(panel_id, DE), 200)
    resp = api_client.approve_design(panel_id, make_qa_headers(qa_user_id))
    return get_success_data(resp, 200)


def walk_panel_to_procurement_cleared(panel_id: str) -> dict:
    """DESIGN_APPROVED -> PROCUREMENT, then receive every BOM line.

    Ends with the panel in PROCUREMENT and all lines RECEIVED/SUBSTITUTED.
    """
    get_success_data(api_client.release_procurement(panel_id, PM), 200)
    lines = get_success_data(api_client.list_panel_components(panel_id, SL), 200)
    for line in lines:
        if line["line_status"] == "ORDERED":
            get_success_data(api_client.receive_panel_component(line["id"], SL), 200)
    return get_success_data(api_client.get_panel(panel_id, PM), 200)


def walk_panel_to_test_passed(panel_id: str, technician_id: str = "tt-100",
                              point_label: str = "TP-1") -> dict:
    """PROCUREMENT -> WIRING -> POINT_TO_POINT -> TEST_PASSED (one PASS point)."""
    get_success_data(api_client.start_wiring(panel_id, SL), 200)
    point = new_test_point(panel_id, point_label=point_label, sequence_no=1)
    get_success_data(api_client.begin_test(panel_id, SL), 200)
    session = get_success_data(
        api_client.create_test_session(
            panel_id, create_test_session_payload(technician_id=technician_id), TT
        ),
        201,
    )
    tech = make_technician_headers(technician_id)
    get_success_data(
        api_client.record_result(
            session["id"], {"test_point_id": point["id"], "outcome": "PASS"}, tech
        ),
        200,
    )
    get_success_data(api_client.complete_test_session(session["id"], tech), 200)
    return {
        "panel": get_success_data(api_client.get_panel(panel_id, PM), 200),
        "test_point": point,
        "test_session": get_success_data(api_client.get_test_session(session["id"], PM), 200),
    }


def walk_panel_to_labeled(panel_id: str, qa_user_id: str = "qa-100",
                          content_hash: str = None,
                          version_tag: str = "v1.0.0",
                          site_backup_taken: bool = False) -> dict:
    """Release a program version (OCC on Panel.version), then request/affix label."""
    panel = get_success_data(api_client.get_panel(panel_id, CE), 200)
    payload = create_program_version_payload(
        expected_panel_version=panel["version"],
        version_tag=version_tag,
        content_hash=content_hash or unique_content_hash(),
        site_backup_taken=site_backup_taken,
    )
    program = get_success_data(api_client.create_program_version(panel_id, payload, CE), 201)
    qa = make_qa_headers(qa_user_id)
    get_success_data(api_client.request_label(panel_id, qa), 200)
    get_success_data(api_client.affix_label(panel_id, qa), 200)
    return {
        "panel": get_success_data(api_client.get_panel(panel_id, PM), 200),
        "program_version": program,
    }


def walk_asbuilt_to_released(panel_id: str, qa_user_id: str = "qa-100") -> dict:
    """Complete the document flags, then PENDING_REVIEW -> APPROVED -> RELEASED."""
    packages = get_success_data(api_client.list_panel_asbuilt_packages(panel_id, DE), 200)
    pkg = packages[0]
    get_success_data(
        api_client.update_asbuilt_package(
            pkg["id"], {"has_wiring_diagram": True, "has_program_archive": True}, DE
        ),
        200,
    )
    get_success_data(
        api_client.approve_asbuilt_package(pkg["id"], make_qa_headers(qa_user_id)), 200
    )
    resp = api_client.release_asbuilt_package(pkg["id"], PM)
    return get_success_data(resp, 200)


def walk_job_to_shipped(job_id: str) -> dict:
    resp = api_client.ship_job(job_id, SHIPPING)
    return get_success_data(resp, 200)


def walk_startup_to_completed(panel_id: str, program_version_id: str,
                              engineer_id: str = "fe-100",
                              session_start: str = DEFAULT_SESSION_START,
                              session_end: str = DEFAULT_SESSION_END,
                              work_time: str = DEFAULT_WORK_TIME,
                              labor_hours: float = 8) -> dict:
    """Schedule a window, take the site backup, start in-window, complete."""
    set_clock(session_start)
    session = get_success_data(
        api_client.create_startup_session(
            panel_id,
            create_startup_session_payload(
                scheduled_start=session_start,
                scheduled_end=session_end,
                engineer_id=engineer_id,
            ),
            PM,
        ),
        201,
    )
    get_success_data(api_client.mark_site_backup(program_version_id, FE), 200)
    set_clock(work_time)
    fe = make_field_engineer_headers(engineer_id)
    get_success_data(api_client.start_startup_session(session["id"], fe), 200)
    get_success_data(
        api_client.complete_startup_session(session["id"], {"labor_hours": labor_hours}, fe),
        200,
    )
    return get_success_data(api_client.get_startup_session(session["id"], PM), 200)


# ---------------------------------------------------------------------------
# Tier 4/5: full-lifecycle composites
# ---------------------------------------------------------------------------

def setup_panel_with_bom(company_name: str = "Pipeline Co",
                         job_number: str = "J-PL1",
                         quoted_price_cents: int = 900000,
                         warranty_months: int = 12,
                         warranty_labor_tier: str = None,
                         site_state_code: str = None,
                         panel_tag: str = "P-PL1",
                         design_engineer_id: str = "de-100",
                         component_spec: dict = None,
                         bom_quantity: int = 1) -> dict:
    """Customer + job + panel + one catalog component + one BOM line (panel in DESIGN)."""
    customer_kwargs = {"company_name": company_name}
    if warranty_labor_tier is not None:
        customer_kwargs["warranty_labor_tier"] = warranty_labor_tier
    if site_state_code is not None:
        customer_kwargs["site_state_code"] = site_state_code
    customer = new_customer(**customer_kwargs)
    job = new_job(
        customer["id"],
        job_number=job_number,
        quoted_price_cents=quoted_price_cents,
        warranty_months=warranty_months,
    )
    panel = new_panel(job["id"], design_engineer_id=design_engineer_id, panel_tag=panel_tag)
    spec = dict(DEFAULT_COMPONENT)
    if component_spec:
        spec.update(component_spec)
    component = new_component(**spec)
    line = add_bom_line(panel["id"], component["id"], quantity=bom_quantity)
    return {
        "customer": customer,
        "job": get_success_data(api_client.get_job(job["id"], PM), 200),
        "panel": get_success_data(api_client.get_panel(panel["id"], PM), 200),
        "component": component,
        "lines": [line],
    }


def setup_panel_through_test_passed(qa_user_id: str = "qa-100",
                                    technician_id: str = "tt-100", **kwargs) -> dict:
    """Panel walked DESIGN -> TEST_PASSED (also sets as-built has_test_report)."""
    ctx = setup_panel_with_bom(**kwargs)
    panel_id = ctx["panel"]["id"]
    walk_panel_to_design_approved(panel_id, qa_user_id)
    walk_panel_to_procurement_cleared(panel_id)
    tested = walk_panel_to_test_passed(panel_id, technician_id)
    ctx.update(tested)
    return ctx


def setup_panel_ready_to_ship(qa_user_id: str = "qa-100",
                              technician_id: str = "tt-100",
                              content_hash: str = None, **kwargs) -> dict:
    """Panel LABELED + as-built RELEASED; job READY_TO_SHIP."""
    ctx = setup_panel_through_test_passed(qa_user_id=qa_user_id,
                                          technician_id=technician_id, **kwargs)
    panel_id = ctx["panel"]["id"]
    labeled = walk_panel_to_labeled(panel_id, qa_user_id, content_hash=content_hash)
    ctx.update(labeled)
    ctx["asbuilt"] = walk_asbuilt_to_released(panel_id, qa_user_id)
    ctx["job"] = get_success_data(api_client.get_job(ctx["job"]["id"], PM), 200)
    return ctx


def setup_shipped_panel(qa_user_id: str = "qa-100", technician_id: str = "tt-100",
                        content_hash: str = None, **kwargs) -> dict:
    """Full shop lifecycle through shipment: panel SHIPPED, job SHIPPED."""
    ctx = setup_panel_ready_to_ship(qa_user_id=qa_user_id, technician_id=technician_id,
                                    content_hash=content_hash, **kwargs)
    ctx["job"] = walk_job_to_shipped(ctx["job"]["id"])
    ctx["panel"] = get_success_data(api_client.get_panel(ctx["panel"]["id"], PM), 200)
    return ctx


def setup_commissioned_job(qa_user_id: str = "qa-100", technician_id: str = "tt-100",
                           engineer_id: str = "fe-100",
                           session_start: str = DEFAULT_SESSION_START,
                           session_end: str = DEFAULT_SESSION_END,
                           work_time: str = DEFAULT_WORK_TIME,
                           labor_hours: float = 8,
                           content_hash: str = None, **kwargs) -> dict:
    """Full lifecycle through commissioning: panel + job COMMISSIONED.

    Sets Job.warranty_expires_at = commissioned_at + warranty_months.
    """
    ctx = setup_shipped_panel(qa_user_id=qa_user_id, technician_id=technician_id,
                              content_hash=content_hash, **kwargs)
    ctx["startup_session"] = walk_startup_to_completed(
        ctx["panel"]["id"], ctx["program_version"]["id"],
        engineer_id=engineer_id, session_start=session_start, session_end=session_end,
        work_time=work_time, labor_hours=labor_hours,
    )
    ctx["panel"] = get_success_data(api_client.get_panel(ctx["panel"]["id"], PM), 200)
    ctx["job"] = get_success_data(api_client.get_job(ctx["job"]["id"], PM), 200)
    return ctx


# ---------------------------------------------------------------------------
# Substitution helpers
# ---------------------------------------------------------------------------

def new_substitution_request(panel_id: str, original_line_id: str,
                             proposed_component_id: str,
                             requested_by: str = "de-100", **overrides) -> dict:
    """Create a SubstitutionRequest with an explicit requester identity (SoD anchor)."""
    payload = create_substitution_request_payload(
        original_line_id, proposed_component_id, **overrides
    )
    resp = api_client.create_substitution_request(
        panel_id, payload, make_designer_headers(requested_by)
    )
    return get_success_data(resp, 201)


# ---------------------------------------------------------------------------
# Change-order / warranty helpers
# ---------------------------------------------------------------------------

def approve_change_order_as_customer(order_id: str, customer_id: str, **payload_kw) -> dict:
    """Fetch the job version fresh, then approve with the OCC field set."""
    order = get_success_data(api_client.get_change_order(order_id, PM), 200)
    job = get_success_data(api_client.get_job(order["job_id"], PM), 200)
    payload = {"expected_job_version": job["version"]}
    payload.update(payload_kw)
    resp = api_client.approve_change_order(
        order_id, payload, make_customer_headers(customer_id)
    )
    return get_success_data(resp, 200)


def file_warranty_claim(job_id: str, panel_id: str, customer_id: str, **overrides) -> dict:
    resp = api_client.create_warranty_claim(
        job_id,
        create_warranty_claim_payload(panel_id, **overrides),
        make_customer_headers(customer_id),
    )
    return get_success_data(resp, 201)
