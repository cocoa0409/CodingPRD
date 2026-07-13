"""Composite setup helpers.

Every test runs against a freshly restarted server with an empty database, so each
helper builds all of its preconditions from scratch using only PRD-declared endpoints.
Setup calls use get_success_data() (lenient) so a broken precondition surfaces as a
clear "Setup failed" rather than a confusing assertion mismatch.

Identity threading: after creating an entity_backed entity (Retailer/Pro/Customer),
ownership-gated calls use make_<role>_headers(entity["id"]) — never the shared constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS, make_retailer_headers, make_pro_headers, make_customer_headers,
)
from .factories import (
    create_retailer_payload, create_service_zone_payload, create_customer_payload,
    create_pro_payload, create_application_payload, create_install_task_payload,
    create_addon_payload, create_work_order_payload, schedule_payload,
    create_part_payload, create_rating_payload,
)

ADMIN = TEST_USERS["admin_headers"]


# --------------------------------------------------------------------------
# Primitive builders
# --------------------------------------------------------------------------
def set_clock(api, iso: str):
    return get_success_data(api.set_clock(iso, ADMIN))


def new_retailer(api, commission_rate_bps=1000, name="Test Retailer"):
    return get_success_data(api.create_retailer(
        create_retailer_payload(name=name, commission_rate_bps=commission_rate_bps), ADMIN))


def suspend_retailer(api, retailer_id):
    return get_success_data(api.update_retailer_status(retailer_id, {"status": "SUSPENDED"}, ADMIN))


def new_zone(api, max_concurrent=5, coverage_active=True, zone_code="Z1", name="Zone"):
    return get_success_data(api.create_service_zone(create_service_zone_payload(
        zone_code=zone_code, name=name, max_concurrent_appointments=max_concurrent,
        coverage_active=coverage_active), ADMIN))


def new_customer(api, full_name="Ada Customer", email="ada@example.com"):
    return get_success_data(api.create_customer(
        create_customer_payload(full_name=full_name, email=email), ADMIN))


def new_pro(api, zone_id, skills=None, full_name="Pat Pro", email="pat@example.com"):
    if skills is None:
        skills = ["TV_MOUNT"]
    return get_success_data(api.create_pro(create_pro_payload(
        service_zone_id=zone_id, skills=skills, full_name=full_name, email=email), ADMIN))


def new_application(api, pro_id, background_check_ref="BG-1"):
    return get_success_data(api.create_application(
        pro_id, create_application_payload(background_check_ref=background_check_ref), ADMIN))


def new_approved_pro(api, zone_id, skills=None, full_name="Pat Pro", email="pat@example.com",
                     background_check_ref="BG-1"):
    """Create a pro + submit + approve its vetting. Returns (pro, application)."""
    pro = new_pro(api, zone_id, skills=skills, full_name=full_name, email=email)
    app = new_application(api, pro["id"], background_check_ref=background_check_ref)
    app = get_success_data(api.approve_application(app["id"], ADMIN))
    return pro, app


def new_task(api, base_price_cents=12000, warranty_days=30, category="TV_MOUNT",
             required_skill="TV_MOUNT", task_code="T1", estimated_minutes=60, name="Task"):
    return get_success_data(api.create_install_task(create_install_task_payload(
        task_code=task_code, name=name, category=category, required_skill=required_skill,
        base_price_cents=base_price_cents, estimated_minutes=estimated_minutes,
        warranty_days=warranty_days), ADMIN))


def new_addon(api, price_cents, category="TV_MOUNT", addon_code="A1", name="AddOn"):
    return get_success_data(api.create_addon(create_addon_payload(
        addon_code=addon_code, name=name, category=category, price_cents=price_cents), ADMIN))


def new_draft_work_order(api, retailer_id, customer_id, task_id, zone_id,
                         product_category="TV_MOUNT", product_sku="S"):
    payload = create_work_order_payload(
        retailer_id=retailer_id, customer_id=customer_id, install_task_id=task_id,
        service_zone_id=zone_id, product_category=product_category, product_sku=product_sku)
    return get_success_data(api.create_work_order(payload, make_retailer_headers(retailer_id)))


def schedule_order(api, wo_id, retailer_id, scheduled_start, scheduled_end, addon_ids=None):
    payload = schedule_payload(scheduled_start=scheduled_start, scheduled_end=scheduled_end)
    if addon_ids is not None:
        payload["selected_addon_ids"] = addon_ids
    return get_success_data(api.schedule_work_order(wo_id, payload, make_retailer_headers(retailer_id)))


def dispatch_order(api, wo_id, expected_version):
    return get_success_data(api.dispatch_work_order(
        wo_id, {"expected_work_order_version": expected_version}, ADMIN))


def offered_assignment_for(api, wo_id):
    """Return the single currently-OFFERED assignment for a work order."""
    data, _ = _list(api.list_assignments(ADMIN, params={"work_order_id": wo_id}))
    offered = [a for a in data if a["status"] == "OFFERED"]
    assert offered, f"no OFFERED assignment for work order {wo_id}"
    return offered[0]


def _list(response):
    """Return (data_list, meta) from a list response (lenient)."""
    body = response.json()
    return body["data"], body.get("meta", {})


def accept_assignment(api, asg_id, pro_id):
    return get_success_data(api.accept_assignment(asg_id, make_pro_headers(pro_id)))


def decline_assignment(api, asg_id, pro_id):
    return get_success_data(api.decline_assignment(asg_id, make_pro_headers(pro_id)))


def start_order(api, wo_id, pro_id):
    return get_success_data(api.start_work_order(wo_id, make_pro_headers(pro_id)))


def add_part(api, wo_id, pro_id, unit_cost_cents, quantity, markup_bps, name="Part"):
    return get_success_data(api.add_part(wo_id, create_part_payload(
        name=name, unit_cost_cents=unit_cost_cents, quantity=quantity, markup_bps=markup_bps),
        make_pro_headers(pro_id)))


def complete_order(api, wo_id, pro_id):
    return get_success_data(api.complete_work_order(wo_id, make_pro_headers(pro_id)))


def request_redo(api, wo_id, customer_id):
    return get_success_data(api.request_redo(wo_id, make_customer_headers(customer_id)))


def close_order(api, wo_id):
    return get_success_data(api.close_work_order(wo_id, ADMIN))


def cancel_order_admin(api, wo_id, reason="cancelled"):
    return get_success_data(api.cancel_work_order(wo_id, {"reason": reason}, ADMIN))


def payout_for(api, wo_id):
    data, _ = _list(api.list_payouts(ADMIN, params={"work_order_id": wo_id}))
    return data[0] if data else None


def settlement_entries_for(api, wo_id):
    data, _ = _list(api.list_settlement_entries(ADMIN, params={"work_order_id": wo_id}))
    return data


# --------------------------------------------------------------------------
# Composite scenario builders
# --------------------------------------------------------------------------
def setup_catalog(api, *, base_price_cents=12000, commission_rate_bps=1000, warranty_days=30,
                  max_concurrent=5, coverage_active=True, category="TV_MOUNT",
                  required_skill="TV_MOUNT"):
    """Retailer + zone + customer + install task. Returns a dict of the created entities."""
    retailer = new_retailer(api, commission_rate_bps=commission_rate_bps)
    zone = new_zone(api, max_concurrent=max_concurrent, coverage_active=coverage_active)
    customer = new_customer(api)
    task = new_task(api, base_price_cents=base_price_cents, warranty_days=warranty_days,
                    category=category, required_skill=required_skill)
    return {"retailer": retailer, "zone": zone, "customer": customer, "task": task}


def setup_scheduled_order(api, *, base_price_cents=12000, commission_rate_bps=1000,
                          warranty_days=30, scheduled_start="2026-03-05T09:00:00Z",
                          scheduled_end="2026-03-05T10:00:00Z", addon_prices=None,
                          max_concurrent=5, category="TV_MOUNT", required_skill="TV_MOUNT",
                          clock=None):
    """Catalog + DRAFT work order advanced to SCHEDULED (with optional add-ons attached).

    Returns a dict: retailer, zone, customer, task, addons(list), wo(scheduled), version.
    """
    if clock is not None:
        set_clock(api, clock)
    ctx = setup_catalog(api, base_price_cents=base_price_cents,
                        commission_rate_bps=commission_rate_bps, warranty_days=warranty_days,
                        max_concurrent=max_concurrent, category=category,
                        required_skill=required_skill)
    addons = []
    addon_ids = None
    if addon_prices:
        for i, price in enumerate(addon_prices):
            addons.append(new_addon(api, price, category=category,
                                    addon_code=f"AO{i}", name=f"AddOn{i}"))
        addon_ids = [a["id"] for a in addons]
    wo = new_draft_work_order(api, ctx["retailer"]["id"], ctx["customer"]["id"],
                              ctx["task"]["id"], ctx["zone"]["id"], product_category=category)
    wo = schedule_order(api, wo["id"], ctx["retailer"]["id"], scheduled_start, scheduled_end,
                        addon_ids=addon_ids)
    ctx.update({"addons": addons, "wo": wo, "version": wo["version"]})
    return ctx


def setup_dispatched_order(api, **kwargs):
    """Scheduled order + one approved pro + dispatch. Returns ctx with pro, app, assignment."""
    ctx = setup_scheduled_order(api, **kwargs)
    pro, app = new_approved_pro(api, ctx["zone"]["id"], skills=["TV_MOUNT"])
    wo = dispatch_order(api, ctx["wo"]["id"], ctx["version"])
    asg = offered_assignment_for(api, ctx["wo"]["id"])
    ctx.update({"pro": pro, "app": app, "wo": wo, "version": wo["version"], "assignment": asg})
    return ctx


def setup_in_progress_order(api, **kwargs):
    """Dispatched order -> accepted -> started (IN_PROGRESS). Returns ctx."""
    ctx = setup_dispatched_order(api, **kwargs)
    accept_assignment(api, ctx["assignment"]["id"], ctx["pro"]["id"])
    wo = start_order(api, ctx["wo"]["id"], ctx["pro"]["id"])
    ctx["wo"] = wo
    ctx["version"] = wo["version"]
    return ctx


def setup_completed_order(api, *, parts=None, **kwargs):
    """Full chain to COMPLETED. `parts` is a list of dicts with unit_cost_cents/quantity/markup_bps
    added between start and complete. Returns ctx with completed wo, payout, and settlement entry.
    """
    ctx = setup_in_progress_order(api, **kwargs)
    added_parts = []
    if parts:
        for i, p in enumerate(parts):
            added_parts.append(add_part(api, ctx["wo"]["id"], ctx["pro"]["id"],
                                        p["unit_cost_cents"], p["quantity"], p["markup_bps"],
                                        name=p.get("name", f"Part{i}")))
    wo = complete_order(api, ctx["wo"]["id"], ctx["pro"]["id"])
    ctx["wo"] = wo
    ctx["version"] = wo["version"]
    ctx["parts"] = added_parts
    ctx["payout"] = payout_for(api, wo["id"])
    ctx["settlement_entries"] = settlement_entries_for(api, wo["id"])
    return ctx
