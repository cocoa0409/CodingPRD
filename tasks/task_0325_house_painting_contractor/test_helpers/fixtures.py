"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() from the framework (lenient validator) so setup failures
produce clear "setup failed" errors, not confusing assertion failures.

The harness restarts the server and clears the database before EVERY test, so
every helper here builds its preconditions from scratch using only PRD endpoints.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_paint_product_payload,
    create_crew_member_payload,
    create_equipment_payload,
    create_weather_window_payload,
    create_project_payload,
    create_surface_payload,
    create_color_selection_payload,
    create_change_order_payload,
    create_crew_assignment_payload,
    create_payment_payload,
    create_warranty_claim_payload,
)
from .test_users import TEST_USERS

EST = TEST_USERS["estimator_headers"]
PM = TEST_USERS["project_manager_headers"]
CUST = TEST_USERS["customer_headers"]
CREW = TEST_USERS["crew_member_headers"]


# ─── Tier 0: Catalog primitives ──────────────────────────────────────────

def create_product(**overrides):
    """Create a paint product. Default INTERIOR / price 4000 / coverage 350."""
    res = api_client.create_paint_product(create_paint_product_payload(**overrides), EST)
    return get_success_data(res)


def create_crew(**overrides):
    """Create a crew member (default MASTER)."""
    res = api_client.create_crew_member(create_crew_member_payload(**overrides), PM)
    return get_success_data(res)


def create_equipment(**overrides):
    res = api_client.create_equipment(create_equipment_payload(**overrides), PM)
    return get_success_data(res)


def create_weather(**overrides):
    res = api_client.create_weather_window(create_weather_window_payload(**overrides), PM)
    return get_success_data(res)


def pin_clock(to_iso8601: str):
    """Pin the server clock for deterministic completion / warranty timestamps."""
    return api_client.set_clock({"to_iso8601": to_iso8601}, PM)


# ─── Tier 1: Project + scope construction ────────────────────────────────

def create_project(**overrides):
    """Create a DRAFT/UNPAID project. Default INTERIOR scope, deposit_pct 30."""
    res = api_client.create_project(create_project_payload(**overrides), EST)
    return get_success_data(res)


def add_surface(project_id, product_id, **overrides):
    """Attach one PLANNED surface (auto-spawns its line item)."""
    res = api_client.create_surface(
        create_surface_payload(project_id, product_id, **overrides), EST)
    return get_success_data(res)


def setup_draft_project_with_surface(product_overrides=None, project_overrides=None,
                                     surface_overrides=None):
    """Product + DRAFT project + one PLANNED surface (default S1: 120/1/LIGHT).

    Returns (product, project, surface).
    """
    product = create_product(**(product_overrides or {}))
    project = create_project(**(project_overrides or {}))
    surface = add_surface(project["id"], product["id"], **(surface_overrides or {}))
    return product, project, surface


def setup_estimated_project(product_overrides=None, project_overrides=None,
                            surfaces=None):
    """Product + project + surfaces, finalized to ESTIMATED.

    `surfaces` is a list of surface override dicts; defaults to a single S1
    (120 sqft, 1 coat, LIGHT). Returns (product, project_after_finalize, surface_list).
    """
    product = create_product(**(product_overrides or {}))
    project = create_project(**(project_overrides or {}))
    if surfaces is None:
        surfaces = [{}]  # one default S1
    created = [add_surface(project["id"], product["id"], **ov) for ov in surfaces]
    finalized = get_success_data(api_client.finalize_estimate(project["id"], EST))
    return product, finalized, created


# ─── Tier 2: Money axis ──────────────────────────────────────────────────

def pay_deposit(project_id, amount_cents):
    """Record a DEPOSIT payment for the exact deposit_due. Returns payment."""
    res = api_client.create_payment(
        create_payment_payload(project_id, "DEPOSIT", amount_cents), CUST)
    return get_success_data(res)


def pay_final(project_id, amount_cents):
    """Record a FINAL payment for the exact balance_due. Returns payment."""
    res = api_client.create_payment(
        create_payment_payload(project_id, "FINAL", amount_cents), CUST)
    return get_success_data(res)


# ─── Tier 2: Color approval ──────────────────────────────────────────────

def propose_color(surface_id, **overrides):
    res = api_client.create_color_selection(
        create_color_selection_payload(surface_id, **overrides), EST)
    return get_success_data(res)


def approve_color(color_selection_id):
    res = api_client.approve_color_selection(color_selection_id, CUST)
    return get_success_data(res)


def propose_and_approve_color(surface_id, **overrides):
    cs = propose_color(surface_id, **overrides)
    return approve_color(cs["id"])


# ─── Tier 2: Crew assignment ─────────────────────────────────────────────

def schedule_crew(project_id, crew_member_id, start_date, end_date, **overrides):
    res = api_client.create_crew_assignment(
        create_crew_assignment_payload(
            project_id, crew_member_id, start_date, end_date, **overrides), PM)
    return get_success_data(res)


# ─── Tier 3: Lifecycle shortcuts ─────────────────────────────────────────

def setup_scheduled_project(deposit_cents, project_overrides=None, surfaces=None,
                            start_date="2026-03-02", end_date="2026-03-03"):
    """Full path to a SCHEDULED project (single default S1 surface unless overridden):
    product -> project -> surface(s) -> finalize -> approve color(s) -> create crew ->
    pay deposit -> schedule.

    Returns dict with product, project (SCHEDULED), surfaces, crew, assignment.
    """
    product, project, created = setup_estimated_project(
        project_overrides=project_overrides, surfaces=surfaces)
    for surface in created:
        propose_and_approve_color(surface["id"])
    crew = create_crew()
    assignment = schedule_crew(project["id"], crew["id"], start_date, end_date)
    pay_deposit(project["id"], deposit_cents)
    scheduled = get_success_data(api_client.schedule_project(project["id"], PM))
    return {
        "product": product,
        "project": scheduled,
        "surfaces": created,
        "crew": crew,
        "assignment": assignment,
    }


def setup_in_progress_project(deposit_cents, **kwargs):
    """SCHEDULED project advanced to IN_PROGRESS (work started)."""
    bundle = setup_scheduled_project(deposit_cents, **kwargs)
    bundle["project"] = get_success_data(
        api_client.start_work(bundle["project"]["id"], PM))
    return bundle


def setup_walkthrough_pending_project(deposit_cents, **kwargs):
    """IN_PROGRESS project advanced to WALKTHROUGH_PENDING: crew begun+completed,
    request-walkthrough fired, a PENDING Walkthrough opened.

    Returns the bundle plus 'walkthrough' (the PENDING walkthrough row).
    """
    bundle = setup_in_progress_project(deposit_cents, **kwargs)
    asg_id = bundle["assignment"]["id"]
    get_success_data(api_client.begin_crew_assignment(asg_id, CREW))
    get_success_data(api_client.complete_crew_assignment(asg_id, CREW))
    bundle["project"] = get_success_data(
        api_client.request_walkthrough(bundle["project"]["id"], PM))
    wts, _ = _list_data(api_client.list_walkthroughs(PM, params={"project_id": bundle["project"]["id"]}))
    bundle["walkthrough"] = wts[0]
    return bundle


def setup_completed_project(deposit_cents, final_cents, completion_iso="2026-04-01T09:00:00Z",
                            **kwargs):
    """Full lifecycle to COMPLETED: walkthrough-pending -> pay final -> pin clock -> pass.

    The clock is pinned BEFORE the pass so warranty_expires_at is deterministic.
    Returns the bundle with the COMPLETED project and the PASSED walkthrough.
    """
    bundle = setup_walkthrough_pending_project(deposit_cents, **kwargs)
    pay_final(bundle["project"]["id"], final_cents)
    pin_clock(completion_iso)
    get_success_data(api_client.pass_walkthrough(bundle["walkthrough"]["id"], CUST))
    bundle["project"] = get_success_data(
        api_client.get_project(bundle["project"]["id"], PM))
    bundle["walkthrough"] = get_success_data(
        api_client.get_walkthrough(bundle["walkthrough"]["id"], PM))
    return bundle


# ─── Tier 3: Change-order shortcuts ──────────────────────────────────────

def create_change_order(project_id, expected_version, action, **overrides):
    res = api_client.create_change_order(
        create_change_order_payload(project_id, expected_version, action, **overrides), EST)
    return get_success_data(res)


def create_submitted_change_order(project_id, expected_version, action, **overrides):
    """Create + submit a change order. Returns the SUBMITTED change order."""
    co = create_change_order(project_id, expected_version, action, **overrides)
    return get_success_data(api_client.submit_change_order(co["id"], EST))


def create_approved_change_order(project_id, expected_version, action, **overrides):
    """Create + submit + approve a change order. Returns the APPROVED change order."""
    co = create_submitted_change_order(project_id, expected_version, action, **overrides)
    return get_success_data(api_client.approve_change_order(co["id"], CUST))


def add_surface_co_overrides(product_id, label="Study", surface_kind="INTERIOR",
                             area=300, coats=2, prep="HEAVY"):
    """Build the new_* override dict for an ADD_SURFACE change order."""
    return {
        "new_label": label,
        "new_surface_kind": surface_kind,
        "new_area_sqft": area,
        "new_coats": coats,
        "new_prep_level": prep,
        "new_paint_product_id": product_id,
    }


# ─── Helpers ─────────────────────────────────────────────────────────────

def _list_data(response):
    """Unwrap a list response into (data_list, raw_json) without strict validation."""
    body = response.json()
    return body.get("data", []), body


def find_line_item_for_surface(project_id, surface_id):
    """Return the LineItem dict whose surface_id matches, by listing line items."""
    data, _ = _list_data(api_client.list_line_items(EST, params={"project_id": project_id}))
    for li in data:
        if li.get("surface_id") == surface_id:
            return li
    return None
