"""Composite setup helpers.

Each test runs against a freshly-restarted, empty server, so every fixture
builds its preconditions from scratch using only PRD-declared endpoints.
Fixtures use get_success_data() (lenient) for setup steps so a setup break
surfaces as a clear "Setup failed" rather than a confusing assertion.

Identity threading: the Customer role is entity-backed, so estimate accept /
warranty claim use make_customer_headers(customer_id) — never the shared
TEST_USERS["customer_headers"] constant.

Standard two-line estimate used across many difficulty instances:
  fence CEDAR/PRIVACY 120 ft, SINGLE_GATE, slope 10  -> line_material_cost 5385.00
  deck  COMPOSITE/DECK_STANDARD 200 sqft, STAIR_SET, slope 20 -> 8988.00
  contract_total 21605.04 (material 14373.00 + labor 6190.00 + tax 1042.04)
"""
from prd_bench_local_runner.testing import get_success_data, build_user_headers
from .api_client import api_client
from .test_users import TEST_USERS, make_customer_headers
from .factories import (
    create_customer_payload, create_project_payload, create_estimate_payload,
    create_line_item_payload, create_site_measure_payload, create_permit_payload,
    create_hoa_approval_payload, create_material_order_payload,
    create_crew_booking_payload, create_change_order_payload,
)

PM = TEST_USERS["project_manager_headers"]
EST = TEST_USERS["estimator_headers"]
FT = TEST_USERS["field_tech_headers"]
PC = TEST_USERS["permit_clerk_headers"]


# ---------------------------------------------------------------------------
# Tier 1: primitive create helpers
# ---------------------------------------------------------------------------
def create_customer(hoa_governed=False, **overrides):
    """Create a Customer. Returns the customer dict."""
    payload = create_customer_payload(hoa_governed=hoa_governed, **overrides)
    return get_success_data(api_client.create_customer(payload, PM))


def create_project(customer_id, job_type="FENCE", **overrides):
    """Create a DRAFT project for a customer. Returns the project dict."""
    payload = create_project_payload(customer_id, job_type=job_type, **overrides)
    return get_success_data(api_client.create_project(payload, PM))


def create_estimate(project_id, **overrides):
    """Create a DRAFT estimate under a project. Returns the estimate dict."""
    payload = create_estimate_payload(**overrides)
    return get_success_data(api_client.create_estimate(project_id, payload, EST))


def add_line_item(estimate_id, **overrides):
    """Add one line item to a DRAFT estimate. Returns the line item dict."""
    payload = create_line_item_payload(estimate_id, **overrides)
    return get_success_data(api_client.create_line_item(payload, EST))


# Line-item spec presets for the canonical estimate.
FENCE_120_GATE_SLOPE10 = dict(
    work_type="FENCE", material="CEDAR", style="PRIVACY",
    quantity_units=120, accessory="SINGLE_GATE", grade_slope_pct=10,
)
DECK_200_STAIRS_SLOPE20 = dict(
    work_type="DECK", material="COMPOSITE", style="DECK_STANDARD",
    quantity_units=200, accessory="STAIR_SET", grade_slope_pct=20,
)
FENCE_100_PLAIN = dict(
    work_type="FENCE", material="CEDAR", style="PRIVACY", quantity_units=100,
)


# ---------------------------------------------------------------------------
# Tier 2: estimate lifecycle shortcuts
# ---------------------------------------------------------------------------
def setup_priced_estimate(line_specs=None, hoa_governed=False, job_type="FENCE_AND_DECK",
                          tax_rate_pct=None):
    """Customer + project + estimate with given line items, then PRICE it.

    Returns a context dict:
      {customer, project, estimate, line_items, customer_headers}
    Project is DRAFT, estimate is PRICED.
    """
    if line_specs is None:
        line_specs = [FENCE_120_GATE_SLOPE10, DECK_200_STAIRS_SLOPE20]
    customer = create_customer(hoa_governed=hoa_governed)
    project = create_project(customer["id"], job_type=job_type)
    est_overrides = {} if tax_rate_pct is None else {"tax_rate_pct": tax_rate_pct}
    estimate = create_estimate(project["id"], **est_overrides)
    line_items = [add_line_item(estimate["id"], **spec) for spec in line_specs]
    get_success_data(api_client.price_estimate(project["id"], estimate["id"], EST))
    return {
        "customer": customer,
        "customer_headers": make_customer_headers(customer["id"]),
        "project": project,
        "estimate": estimate,
        "line_items": line_items,
    }


def setup_accepted_estimate(line_specs=None, hoa_governed=False,
                            job_type="FENCE_AND_DECK", tax_rate_pct=None):
    """Priced estimate then ACCEPTED by the owning customer.

    Project becomes ESTIMATED with four SCHEDULED draws. Returns the same
    context dict as setup_priced_estimate (fields refreshed).
    """
    ctx = setup_priced_estimate(line_specs=line_specs, hoa_governed=hoa_governed,
                                job_type=job_type, tax_rate_pct=tax_rate_pct)
    get_success_data(api_client.accept_estimate(
        ctx["project"]["id"], ctx["estimate"]["id"], ctx["customer_headers"]))
    ctx["project"] = get_success_data(api_client.get_project(ctx["project"]["id"], PM))
    return ctx


def setup_measured_project(line_specs=None, measured_quantities=None,
                           hoa_governed=False, job_type="FENCE_AND_DECK"):
    """Accepted estimate + recorded + APPROVED site measure -> project MEASURED.

    If measured_quantities is None, every line is re-measured at its original
    quantity (no reconciliation drift). Returns context dict with added keys:
      site_measure
    """
    ctx = setup_accepted_estimate(line_specs=line_specs, hoa_governed=hoa_governed,
                                  job_type=job_type)
    if measured_quantities is None:
        measured_quantities = [
            {"line_item_id": li["id"], "measured_units": li["quantity_units"]}
            for li in ctx["line_items"]
        ]
    sm = get_success_data(api_client.create_site_measure(
        ctx["project"]["id"], create_site_measure_payload(measured_quantities), FT))
    ctx["site_measure"] = get_success_data(api_client.approve_site_measure(
        ctx["project"]["id"], sm["id"], PM))
    ctx["site_measure_id"] = sm["id"]
    # Refresh canonical project (now MEASURED, contract_total reconciled).
    ctx["project"] = get_success_data(api_client.get_project(ctx["project"]["id"], PM))
    return ctx


def issue_fence_permit(project_id):
    """Create + submit + ISSUE a FENCE_PERMIT. Returns the permit dict (post-issue)."""
    permit = get_success_data(api_client.create_permit(
        project_id, create_permit_payload(), PC))
    get_success_data(api_client.submit_permit(project_id, permit["id"], PC))
    return get_success_data(api_client.decide_permit(
        project_id, permit["id"], {"decision": "ISSUE"}, PC))


def setup_approved_project(line_specs=None, hoa_governed=False,
                           job_type="FENCE_AND_DECK", measured_quantities=None):
    """Project advanced to APPROVED for a non-HOA customer: measured + permit
    issued (permit_clearance CLEARED). Returns context dict with added keys:
      permit
    """
    ctx = setup_measured_project(line_specs=line_specs, hoa_governed=hoa_governed,
                                 job_type=job_type, measured_quantities=measured_quantities)
    ctx["permit"] = issue_fence_permit(ctx["project"]["id"])
    ctx["project"] = get_success_data(api_client.get_project(ctx["project"]["id"], PM))
    return ctx


def add_confirmed_material_order(project_id, dock_id="DOCK_1",
                                 delivery_window_start="2026-07-01T08:00:00Z",
                                 delivery_window_end="2026-07-01T12:00:00Z",
                                 **overrides):
    """Place + confirm a material order on a project that has an APPROVED site
    measure. Returns the CONFIRMED order dict."""
    payload = create_material_order_payload(
        dock_id=dock_id, delivery_window_start=delivery_window_start,
        delivery_window_end=delivery_window_end, **overrides)
    mo = get_success_data(api_client.create_material_order(project_id, payload, PM))
    return get_success_data(api_client.confirm_material_order(project_id, mo["id"], PM))


def add_delivered_material_order(project_id, **overrides):
    """Place + confirm + deliver a material order. Returns the DELIVERED order."""
    mo = add_confirmed_material_order(project_id, **overrides)
    return get_success_data(api_client.deliver_material_order(project_id, mo["id"], FT))


def add_confirmed_crew_booking(project_id, crew_id="CREW_1",
                               window_start="2026-07-20T08:00:00Z",
                               window_end="2026-07-20T17:00:00Z"):
    """Hold + confirm a crew booking. Requires project APPROVED with a
    CONFIRMED/DELIVERED material order. Returns the CONFIRMED booking dict."""
    cb = get_success_data(api_client.create_crew_booking(
        project_id, create_crew_booking_payload(
            crew_id=crew_id, window_start=window_start, window_end=window_end), FT))
    return get_success_data(api_client.confirm_crew_booking(project_id, cb["id"], FT))


# ---------------------------------------------------------------------------
# Tier 3: scheduled / in-progress / completed shortcuts
# ---------------------------------------------------------------------------
def setup_scheduled_project(line_specs=None, dock_id="DOCK_SCHED",
                            crew_id="CREW_SCHED", deliver=True):
    """Full chain to SCHEDULED: approved project + (confirmed or delivered)
    material order + confirmed crew booking. Returns context dict with keys:
      material_order, crew_booking, plus those from setup_approved_project.
    """
    ctx = setup_approved_project(line_specs=line_specs)
    pid = ctx["project"]["id"]
    if deliver:
        ctx["material_order"] = add_delivered_material_order(pid, dock_id=dock_id)
    else:
        ctx["material_order"] = add_confirmed_material_order(pid, dock_id=dock_id)
    ctx["crew_booking"] = add_confirmed_crew_booking(pid, crew_id=crew_id)
    ctx["project"] = get_success_data(api_client.get_project(pid, PM))
    return ctx


def get_draws(project_id):
    """Return the project's draw list (sorted by created_at, i.e. milestone order)."""
    data, _meta = _paginated(api_client.list_draws(project_id, PM))
    return data


def _paginated(response):
    body = response.json()
    return body["data"], body.get("meta", {})


def setup_in_progress_project(line_specs=None):
    """Chain to IN_PROGRESS: scheduled project, DEPOSIT draw invoiced + paid.

    Returns context dict with added keys: draws (list), deposit_draw.
    """
    ctx = setup_scheduled_project(line_specs=line_specs, dock_id="DOCK_INP",
                                  crew_id="CREW_INP")
    pid = ctx["project"]["id"]
    draws = get_draws(pid)
    deposit = next(d for d in draws if d["milestone"] == "DEPOSIT")
    get_success_data(api_client.invoice_draw(pid, deposit["id"], PM))
    get_success_data(api_client.pay_draw(pid, deposit["id"], PM))
    ctx["draws"] = get_draws(pid)
    ctx["deposit_draw"] = next(d for d in ctx["draws"] if d["milestone"] == "DEPOSIT")
    ctx["project"] = get_success_data(api_client.get_project(pid, PM))
    return ctx


def setup_completed_project(line_specs=None):
    """Drive a single-fence-line project all the way to COMPLETED.

    DEPOSIT invoiced+paid -> DELIVERY paid (delivered order invoiced it) ->
    FRAMING invoiced+paid -> FINAL invoiced+paid. Returns context dict with
    keys: draws, warranty (the ISSUED warranty), plus scheduled-chain keys.
    """
    if line_specs is None:
        line_specs = [FENCE_100_PLAIN]
    ctx = setup_scheduled_project(line_specs=line_specs, dock_id="DOCK_DONE",
                                  crew_id="CREW_DONE", deliver=True)
    pid = ctx["project"]["id"]
    draws = get_draws(pid)
    by_ms = {d["milestone"]: d for d in draws}
    # DEPOSIT: invoice + pay -> IN_PROGRESS
    get_success_data(api_client.invoice_draw(pid, by_ms["DEPOSIT"]["id"], PM))
    get_success_data(api_client.pay_draw(pid, by_ms["DEPOSIT"]["id"], PM))
    # DELIVERY: already INVOICED by deliver side effect -> pay
    get_success_data(api_client.pay_draw(pid, by_ms["DELIVERY"]["id"], PM))
    # FRAMING: invoice (project IN_PROGRESS) + pay
    get_success_data(api_client.invoice_draw(pid, by_ms["FRAMING"]["id"], PM))
    get_success_data(api_client.pay_draw(pid, by_ms["FRAMING"]["id"], PM))
    # FINAL: invoice + pay -> COMPLETED + warranty
    get_success_data(api_client.invoice_draw(pid, by_ms["FINAL"]["id"], PM))
    get_success_data(api_client.pay_draw(pid, by_ms["FINAL"]["id"], PM))
    ctx["draws"] = get_draws(pid)
    warranties, _ = _paginated(api_client.list_warranties(pid, PM))
    ctx["warranty"] = warranties[0] if warranties else None
    ctx["project"] = get_success_data(api_client.get_project(pid, PM))
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: change-order helpers (OCC + reprice)
# ---------------------------------------------------------------------------
def project_version(project_id):
    """Current Project.version (for OCC expected_project_version)."""
    return get_success_data(api_client.get_project(project_id, PM))["version"]


def draft_change_order(project_id, line_item_id, expected_project_version,
                       **overrides):
    """Draft a change order. Returns the DRAFT change order dict."""
    payload = create_change_order_payload(
        project_id, line_item_id, expected_project_version, **overrides)
    return get_success_data(api_client.create_change_order(payload, PM))
