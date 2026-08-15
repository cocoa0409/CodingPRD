"""Composite setup helpers for multi-step test prerequisites.

Built from the PRD's business workflows (§3.1–§3.9). All helpers use the
lenient get_success_data() validator so setup failures surface as clear
"errors in setup" rather than confusing assertion failures deep in a test.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_START, DEFAULT_SCHEDULED_DATE, DISPATCH_MORNING
from .factories import (
    create_bundle_return_payload,
    create_boom_truck_payload,
    create_contractor_account_payload,
    create_lock_payload,
    create_payment_payload,
    create_product_payload,
    create_project_payload,
    create_stocking_drop_payload,
    create_stocking_order_payload,
    create_takeoff_line_payload,
    create_takeoff_payload,
)
from .test_users import TEST_USERS

CM = TEST_USERS["credit_manager_headers"]
EST = TEST_USERS["estimator_headers"]
DISP = TEST_USERS["dispatcher_headers"]
FORE = TEST_USERS["foreman_headers"]
AR = TEST_USERS["accounts_receivable_headers"]
WH = TEST_USERS["warehouse_manager_headers"]


# ─── Tier 0: clock + single-entity creators ──────────────────────────

def set_logical_clock(to_iso8601: str = CLOCK_START) -> dict:
    """Set the server's logical clock (PRD §2.6). CreditManager only."""
    return get_success_data(api_client.set_current_utc({"to_iso8601": to_iso8601}, CM))


def create_account(**overrides) -> dict:
    return get_success_data(
        api_client.create_contractor_account(create_contractor_account_payload(**overrides), CM))


def create_product(**overrides) -> dict:
    return get_success_data(
        api_client.create_product(create_product_payload(**overrides), WH))


def create_boom_truck(**overrides) -> dict:
    return get_success_data(
        api_client.create_boom_truck(create_boom_truck_payload(**overrides), DISP))


def create_project(account_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_project(create_project_payload(account_id, **overrides), EST))


def get_project(project_id: str) -> dict:
    return get_success_data(api_client.get_project(project_id, CM))


def get_account(account_id: str) -> dict:
    return get_success_data(api_client.get_contractor_account(account_id, CM))


def get_takeoff(takeoff_id: str) -> dict:
    return get_success_data(api_client.get_takeoff(takeoff_id, EST))


# ─── Tier 1: state progression primitives ────────────────────────────

def create_takeoff_with_lines(project_id: str, lines, **takeoff_overrides):
    """Create a DRAFT takeoff and add lines. `lines` is a list of
    (product_id, sheet_count) tuples. Returns (takeoff, [line, ...])."""
    takeoff = get_success_data(
        api_client.create_takeoff(create_takeoff_payload(project_id, **takeoff_overrides), EST))
    line_objs = []
    for product_id, sheet_count in lines:
        line_objs.append(get_success_data(api_client.add_takeoff_line(
            takeoff["id"], create_takeoff_line_payload(product_id, sheet_count), EST)))
    return takeoff, line_objs


def submit_takeoff(takeoff_id: str) -> dict:
    return get_success_data(api_client.submit_takeoff(takeoff_id, EST))


def lock_takeoff(takeoff_id: str) -> dict:
    """Read the takeoff's current version, then lock with it (PRD §2.9 OCC)."""
    current = get_takeoff(takeoff_id)
    return get_success_data(
        api_client.lock_takeoff(takeoff_id, create_lock_payload(current["version"]), EST))


def open_stocking(project_id: str) -> dict:
    return get_success_data(api_client.open_stocking(project_id, FORE))


def create_stocking_order_with_drops(project_id: str, takeoff_id: str, boom_truck_id: str,
                                     drops, scheduled_date: str = DEFAULT_SCHEDULED_DATE,
                                     shift_window: str = "AM"):
    """Create a DRAFT stocking order and add drops. `drops` is a list of
    (product_id, bundle_count) tuples. Returns (order, [drop, ...])."""
    order = get_success_data(api_client.create_stocking_order(
        create_stocking_order_payload(
            project_id, takeoff_id, boom_truck_id,
            scheduled_date=scheduled_date, shift_window=shift_window),
        DISP))
    drop_objs = []
    for product_id, bundle_count in drops:
        drop_objs.append(get_success_data(api_client.add_stocking_drop(
            order["id"], create_stocking_drop_payload(product_id, bundle_count=bundle_count), DISP)))
    return order, drop_objs


def schedule_order(order_id: str) -> dict:
    return get_success_data(api_client.schedule_stocking_order(order_id, DISP))


def dispatch_order(order_id: str) -> dict:
    return get_success_data(api_client.dispatch_stocking_order(order_id, DISP))


def mark_order_stocked(order_id: str) -> dict:
    return get_success_data(api_client.mark_stocked(order_id, FORE))


# ─── Tier 2/3: composite lifecycle scenarios ─────────────────────────

def create_locked_takeoff(project_id: str, lines, pre_lock_price_patch=None,
                          **takeoff_overrides) -> dict:
    """Create takeoff + lines → submit → optionally patch a product price
    (pre_lock_price_patch=(product_id, new_price)) → lock. Returns LOCKED takeoff."""
    takeoff, _lines = create_takeoff_with_lines(project_id, lines, **takeoff_overrides)
    submit_takeoff(takeoff["id"])
    if pre_lock_price_patch is not None:
        product_id, new_price = pre_lock_price_patch
        get_success_data(api_client.update_product(
            product_id, {"unit_price_cents_per_sheet": new_price}, WH))
    return lock_takeoff(takeoff["id"])


def setup_locked_takeoff_scenario(*, sheet_count=20, account_overrides=None,
                                  product_overrides=None, project_overrides=None,
                                  waste_pct_bp_override=None, pre_lock_price_patch_on_product=False,
                                  pre_lock_price=None, set_clock=True) -> dict:
    """Account (ACTIVE) + Product + Project + Takeoff(line) → SUBMITTED → LOCKED.

    Returns {"account", "product", "project", "takeoff"}.
    """
    if set_clock:
        set_logical_clock()
    account = create_account(**(account_overrides or {}))
    product = create_product(**(product_overrides or {}))
    project = create_project(account["id"], **(project_overrides or {}))
    takeoff_kwargs = {}
    if waste_pct_bp_override is not None:
        takeoff_kwargs["waste_pct_bp_override"] = waste_pct_bp_override
    patch = (product["id"], pre_lock_price) if pre_lock_price is not None else None
    takeoff = create_locked_takeoff(
        project["id"], [(product["id"], sheet_count)],
        pre_lock_price_patch=patch, **takeoff_kwargs)
    return {"account": account, "product": product, "project": project, "takeoff": takeoff}


def setup_stocking_open_scenario(*, truck_overrides=None, **kwargs) -> dict:
    """Locked-takeoff scenario + project opened for stocking + a boom truck.
    Returns dict with keys account/product/project/takeoff/truck."""
    ctx = setup_locked_takeoff_scenario(**kwargs)
    ctx["project"] = open_stocking(ctx["project"]["id"])
    ctx["truck"] = create_boom_truck(**(truck_overrides or {}))
    return ctx


def setup_draft_order_scenario(*, scheduled_date=DEFAULT_SCHEDULED_DATE, shift_window="AM",
                               bundle_count=1, drops=None, **kwargs) -> dict:
    """Stocking-open scenario + DRAFT order with drops (not yet scheduled)."""
    ctx = setup_stocking_open_scenario(**kwargs)
    if drops is None:
        drops = [(ctx["product"]["id"], bundle_count)]
    order, drop_objs = create_stocking_order_with_drops(
        ctx["project"]["id"], ctx["takeoff"]["id"], ctx["truck"]["id"],
        drops, scheduled_date=scheduled_date, shift_window=shift_window)
    ctx["order"] = order
    ctx["drops"] = drop_objs
    return ctx


def setup_scheduled_order_scenario(**kwargs) -> dict:
    """Draft-order scenario + schedule. Order is SCHEDULED with provisional freight."""
    ctx = setup_draft_order_scenario(**kwargs)
    ctx["order"] = schedule_order(ctx["order"]["id"])
    return ctx


def setup_stocked_order_scenario(*, dispatch_time=DISPATCH_MORNING, **kwargs) -> dict:
    """Full chain through STOCKED: schedule → clock to dispatch day → dispatch →
    mark-stocked. The automatic DrawRequest (ISSUED) now exists for the project."""
    ctx = setup_scheduled_order_scenario(**kwargs)
    set_logical_clock(dispatch_time)
    ctx["order"] = dispatch_order(ctx["order"]["id"])
    ctx["order"] = mark_order_stocked(ctx["order"]["id"])
    return ctx


# ─── Tier 3b: draw / payment / return helpers ────────────────────────

def get_draws_for_project(project_id: str) -> list:
    """List draw requests for a project (PRD §3.8 filter)."""
    res = api_client.list_draw_requests(CM, params={"project_id": project_id})
    return get_success_data(res)


def get_single_draw_for_project(project_id: str) -> dict:
    draws = get_draws_for_project(project_id)
    assert len(draws) == 1, f"Setup expected exactly one draw for project, got {len(draws)}"
    return draws[0]


def apply_payment(draw_id: str, amount_cents: int, received_at="2026-08-03T00:00:00Z") -> dict:
    return get_success_data(
        api_client.apply_payment(draw_id, create_payment_payload(amount_cents, received_at=received_at), AR))


def file_bundle_return(stocking_order_id: str, product_id: str,
                       bundles_returned=1, loose_sheets_returned=0) -> dict:
    return get_success_data(api_client.create_bundle_return(
        create_bundle_return_payload(
            stocking_order_id, product_id,
            bundles_returned=bundles_returned, loose_sheets_returned=loose_sheets_returned),
        WH))
