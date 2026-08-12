"""Composite setup helpers for the railcar repair shop domain.

Every fixture builds its preconditions from scratch through the public API:
the harness restarts the server before each test, so nothing carries over.

Layering:
  Tier 1  atomic builders (one POST each, parsed data returned)
  Tier 2  party/shop context: setup_shop_ctx
  Tier 3  railcar + completed inspection: add_car_with_inspection
  Tier 4  work-order lifecycle: build_work_order ... run_to_completed
  Tier 5  billing lifecycle: create_brc_for_current_wo, submit_current_brc
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import (
    BASE_CLOCK_ISO, DEFAULT_SLOT_END, DEFAULT_SLOT_START, DEFECT_AIR_HOSE,
    ENTRY_AIR_HOSE, FOREMAN_USER_ID, QI_USER_ID,
)
from .factories import (
    create_car_owner_payload, create_defect_payload, create_handling_line_payload,
    create_part_payload, create_price_master_entry_payload, create_railcar_payload,
    create_shop_payload, create_shop_slot_payload, create_wheelset_payload,
    create_work_order_payload, create_repair_line_payload, line_actual,
)
from .test_users import (
    TEST_USERS, make_car_owner_rep_headers, make_handling_line_rep_headers,
    make_quality_inspector_headers, make_repair_foreman_headers,
)

ADMIN = TEST_USERS["shop_admin"]
YARD = TEST_USERS["yard_clerk"]
INSPECTOR = TEST_USERS["car_inspector"]
PARTS = TEST_USERS["parts_clerk"]
BILLING = TEST_USERS["billing_clerk"]
QI = TEST_USERS["quality_inspector"]
ANY = TEST_USERS["shop_admin"]  # reads are open to any declared role


# ---------------------------------------------------------------------------
# Tier 1: atomic builders
# ---------------------------------------------------------------------------

def set_clock(iso: str) -> dict:
    return get_success_data(api_client.set_clock({"to_iso8601": iso}, ADMIN))


def create_shop(**overrides) -> dict:
    return get_success_data(api_client.create_shop(create_shop_payload(**overrides), ADMIN))


def create_car_owner(shop_id, **overrides) -> dict:
    return get_success_data(api_client.create_car_owner(create_car_owner_payload(shop_id, **overrides), ADMIN))


def create_handling_line(shop_id, **overrides) -> dict:
    return get_success_data(api_client.create_handling_line(create_handling_line_payload(shop_id, **overrides), ADMIN))


def create_price_entry(shop_id, **overrides) -> dict:
    return get_success_data(api_client.create_price_master_entry(
        create_price_master_entry_payload(shop_id, **overrides), ADMIN))


def create_part(shop_id, **overrides) -> dict:
    return get_success_data(api_client.create_part(create_part_payload(shop_id, **overrides), ADMIN))


def create_wheelset(shop_id, **overrides) -> dict:
    return get_success_data(api_client.create_wheelset(create_wheelset_payload(shop_id, **overrides), PARTS))


def create_slot(shop_id, starts_at=DEFAULT_SLOT_START, ends_at=DEFAULT_SLOT_END, stall_id="S1") -> dict:
    return get_success_data(api_client.create_shop_slot(
        create_shop_slot_payload(shop_id, stall_id=stall_id, starts_at=starts_at, ends_at=ends_at), ADMIN))


def create_railcar(shop_id, owner_id, handling_line_id, **overrides) -> dict:
    return get_success_data(api_client.create_railcar(
        create_railcar_payload(shop_id, owner_id, handling_line_id, **overrides), YARD))


def open_inspection(railcar_id) -> dict:
    return get_success_data(api_client.create_inspection(railcar_id, INSPECTOR))


def add_defect(inspection_id, **overrides) -> dict:
    return get_success_data(api_client.create_defect(inspection_id, create_defect_payload(**overrides), INSPECTOR))


def complete_inspection(inspection_id) -> dict:
    return get_success_data(api_client.complete_inspection(inspection_id, INSPECTOR))


def get_railcar(railcar_id) -> dict:
    return get_success_data(api_client.get_railcar(railcar_id, ANY))


def get_work_order(wo_id) -> dict:
    return get_success_data(api_client.get_work_order(wo_id, ANY))


def get_repair_line(line_id) -> dict:
    return get_success_data(api_client.get_repair_line(line_id, ANY))


def get_part(part_id) -> dict:
    return get_success_data(api_client.get_part(part_id, ANY))


def get_brc(brc_id) -> dict:
    return get_success_data(api_client.get_billing_repair_card(brc_id, ANY))


def get_brc_line(brc_line_id) -> dict:
    return get_success_data(api_client.get_brc_line(brc_line_id, ANY))


def get_counter_bill(cb_id) -> dict:
    return get_success_data(api_client.get_counter_bill(cb_id, ANY))


def get_car_owner(owner_id) -> dict:
    return get_success_data(api_client.get_car_owner(owner_id, ANY))


def get_handling_line(line_id) -> dict:
    return get_success_data(api_client.get_handling_line(line_id, ANY))


def get_inspection(inspection_id) -> dict:
    return get_success_data(api_client.get_inspection(inspection_id, ANY))


def get_wheelset(wheelset_id) -> dict:
    return get_success_data(api_client.get_wheelset(wheelset_id, ANY))


def get_slot(slot_id) -> dict:
    return get_success_data(api_client.get_shop_slot(slot_id, ANY))


def get_warranty_claim(claim_id) -> dict:
    return get_success_data(api_client.get_warranty_claim(claim_id, ANY))


def list_brc_lines(brc_id) -> list:
    data, _meta = validate_paginated(api_client.list_brc_lines_of_card(brc_id, ANY))
    return data


# ---------------------------------------------------------------------------
# Tier 2: shop + parties context
# ---------------------------------------------------------------------------

def setup_shop_ctx(clock=BASE_CLOCK_ISO, shop_overrides=None) -> dict:
    """Pin the logical clock, then create shop + car owner + handling line."""
    if clock is not None:
        set_clock(clock)
    shop = create_shop(**(shop_overrides or {}))
    owner = create_car_owner(shop["id"])
    line = create_handling_line(shop["id"])
    return {"shop": shop, "owner": owner, "line": line, "entries": [], "parts": {}}


def add_price_entry(ctx, **overrides) -> dict:
    entry = create_price_entry(ctx["shop"]["id"], **overrides)
    ctx.setdefault("entries", []).append(entry)
    return entry


def add_part(ctx, key="part", **overrides) -> dict:
    part = create_part(ctx["shop"]["id"], **overrides)
    ctx.setdefault("parts", {})[key] = part
    return part


# ---------------------------------------------------------------------------
# Tier 3: railcar + inspection + defects
# ---------------------------------------------------------------------------

def add_car_with_inspection(ctx, car_number="1001", defects=None, complete=True,
                            reporting_mark="OWNA", built_date="2020-01-15") -> dict:
    car = create_railcar(ctx["shop"]["id"], ctx["owner"]["id"], ctx["line"]["id"],
                         car_number=car_number, reporting_mark=reporting_mark,
                         built_date=built_date)
    insp = open_inspection(car["id"])
    found = [add_defect(insp["id"], **d) for d in (defects if defects is not None else [DEFECT_AIR_HOSE])]
    if complete:
        complete_inspection(insp["id"])
    ctx.update({"car": car, "inspection": get_inspection(insp["id"]), "defects": found})
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: work-order lifecycle
# ---------------------------------------------------------------------------

def create_wo_for_car(ctx, routing="SHOP", foreman=FOREMAN_USER_ID, expected_railcar_version=None) -> dict:
    """Create a work order against the context car. When no explicit expected
    version is given, the railcar's live version is fetched (PRD §2.11 OCC)."""
    car = get_railcar(ctx["car"]["id"])
    version = expected_railcar_version if expected_railcar_version is not None else car["version"]
    payload = create_work_order_payload(car["id"], ctx["inspection"]["id"], version, routing=routing)
    return get_success_data(api_client.create_work_order(payload, make_repair_foreman_headers(foreman)))


def add_line_to_wo(wo_id, defect_finding_id, job_code, planned_parts=None, foreman=FOREMAN_USER_ID) -> dict:
    payload = create_repair_line_payload(defect_finding_id, job_code)
    if planned_parts is not None:
        payload["planned_parts"] = planned_parts
    return get_success_data(api_client.add_repair_line(wo_id, payload, make_repair_foreman_headers(foreman)))


def build_work_order(ctx, routing="SHOP", lines=None, foreman=FOREMAN_USER_ID) -> dict:
    """DRAFT work order with the requested repair lines.

    lines: list of dicts {job_code, defect_index (default 0) | defect_id, planned_parts}.
    Default: a single line on defect 0 priced by the first entry's job_code.
    """
    if lines is None:
        default_job = ctx["entries"][0]["job_code"] if ctx.get("entries") else ENTRY_AIR_HOSE["job_code"]
        lines = [{"job_code": default_job}]
    wo = create_wo_for_car(ctx, routing=routing, foreman=foreman)
    rls = []
    for spec in lines:
        defect_id = spec.get("defect_id") or ctx["defects"][spec.get("defect_index", 0)]["id"]
        rls.append(add_line_to_wo(wo["id"], defect_id, spec["job_code"],
                                  spec.get("planned_parts"), foreman=foreman))
    ctx.update({"wo": wo, "wo_lines": rls})
    return ctx


def submit_current_wo(ctx, foreman=FOREMAN_USER_ID) -> dict:
    ctx["wo"] = get_success_data(api_client.submit_work_order(ctx["wo"]["id"], make_repair_foreman_headers(foreman)))
    return ctx["wo"]


def _party_headers_for(wo, ctx) -> dict:
    """Resolve the authorizing/accepting party from the work order's
    determined responsible_party (PRD §2.1 party-match rule)."""
    party = wo.get("responsible_party")
    if party == "HANDLING_LINE":
        return make_handling_line_rep_headers(ctx["line"]["id"])
    # OWNER or SHARED authorize/accept through the car owner.
    return make_car_owner_rep_headers(ctx["owner"]["id"])


def authorize_current_wo(ctx) -> dict:
    wo = get_work_order(ctx["wo"]["id"])
    headers = _party_headers_for(wo, ctx)
    ctx["wo"] = get_success_data(api_client.authorize_work_order(
        wo["id"], {"expected_work_order_version": wo["version"]}, headers))
    return ctx["wo"]


def assign_slot_current_wo(ctx, slot=None, foreman=FOREMAN_USER_ID, **slot_kwargs) -> dict:
    if slot is None:
        slot = create_slot(ctx["shop"]["id"], **slot_kwargs)
    ctx["slot"] = slot
    ctx["wo"] = get_success_data(api_client.assign_slot(
        ctx["wo"]["id"], {"slot_id": slot["id"]}, make_repair_foreman_headers(foreman)))
    return ctx["wo"]


def dispatch_current_wo(ctx, crew="crew-7", foreman=FOREMAN_USER_ID) -> dict:
    ctx["wo"] = get_success_data(api_client.dispatch_work_order(
        ctx["wo"]["id"], {"mobile_crew_id": crew}, make_repair_foreman_headers(foreman)))
    return ctx["wo"]


def start_current_wo(ctx, foreman=FOREMAN_USER_ID) -> dict:
    ctx["wo"] = get_success_data(api_client.start_work_order(ctx["wo"]["id"], make_repair_foreman_headers(foreman)))
    return ctx["wo"]


def complete_current_wo(ctx, actual_hours=1.5, parts_used=None, foreman=FOREMAN_USER_ID) -> dict:
    """Report completion. actual_hours is a scalar (applied to every line) or a
    list parallel to ctx['wo_lines']. parts_used is None (-> [] everywhere) or a
    list parallel to ctx['wo_lines'] of parts_used lists."""
    hours_list = actual_hours if isinstance(actual_hours, (list, tuple)) else [actual_hours] * len(ctx["wo_lines"])
    parts_list = parts_used if parts_used is not None else [[] for _ in ctx["wo_lines"]]
    actuals = [line_actual(rl["id"], h, p) for rl, h, p in zip(ctx["wo_lines"], hours_list, parts_list)]
    ctx["wo"] = get_success_data(api_client.complete_work_order(
        ctx["wo"]["id"], {"line_actuals": actuals}, make_repair_foreman_headers(foreman)))
    return ctx["wo"]


def qa_current_wo(ctx, result="PASS", reviewer=QI_USER_ID, notes=None) -> dict:
    payload = {"result": result}
    if notes is not None:
        payload["notes"] = notes
    ctx["wo"] = get_success_data(api_client.qa_review_work_order(
        ctx["wo"]["id"], payload, make_quality_inspector_headers(reviewer)))
    return ctx["wo"]


def run_wo_to_completed(ctx, routing="SHOP", actual_hours=1.5, parts_used=None,
                        slot_kwargs=None, foreman=FOREMAN_USER_ID, reviewer=QI_USER_ID) -> dict:
    """From AUTHORIZED: assign slot (SHOP) or dispatch (MOBILE), start, complete, QA PASS."""
    if routing == "SHOP":
        assign_slot_current_wo(ctx, **(slot_kwargs or {}))
    else:
        dispatch_current_wo(ctx, foreman=foreman)
    start_current_wo(ctx, foreman=foreman)
    complete_current_wo(ctx, actual_hours=actual_hours, parts_used=parts_used, foreman=foreman)
    qa_current_wo(ctx, result="PASS", reviewer=reviewer)
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: billing lifecycle
# ---------------------------------------------------------------------------

def create_brc_for_current_wo(ctx) -> dict:
    wo = get_work_order(ctx["wo"]["id"])
    ctx["brc"] = get_success_data(api_client.create_billing_repair_card(
        {"work_order_id": wo["id"], "expected_work_order_version": wo["version"]}, BILLING))
    return ctx["brc"]


def submit_current_brc(ctx) -> dict:
    ctx["brc"] = get_success_data(api_client.submit_billing_repair_card(ctx["brc"]["id"], BILLING))
    ctx["brc_lines"] = list_brc_lines(ctx["brc"]["id"])
    return ctx["brc"]


def accept_current_brc(ctx) -> dict:
    wo = get_work_order(ctx["wo"]["id"])
    headers = _party_headers_for(wo, ctx)
    ctx["brc"] = get_success_data(api_client.accept_billing_repair_card(ctx["brc"]["id"], headers))
    return ctx["brc"]


def settle_current_brc(ctx) -> dict:
    ctx["brc"] = get_success_data(api_client.settle_billing_repair_card(ctx["brc"]["id"], BILLING))
    return ctx["brc"]


def file_counter_bill(ctx, items, filer="owner") -> dict:
    headers = (make_car_owner_rep_headers(ctx["owner"]["id"]) if filer == "owner"
               else make_handling_line_rep_headers(ctx["line"]["id"]))
    return get_success_data(api_client.create_counter_bill(ctx["brc"]["id"], {"items": items}, headers))


def file_warranty_claim(ctx, repair_line_id, filer="owner", **overrides) -> dict:
    from .factories import create_warranty_claim_payload
    headers = (make_car_owner_rep_headers(ctx["owner"]["id"]) if filer == "owner"
               else make_handling_line_rep_headers(ctx["line"]["id"]))
    return get_success_data(api_client.create_warranty_claim(
        create_warranty_claim_payload(repair_line_id, **overrides), headers))


# ---------------------------------------------------------------------------
# Full-pipeline scenario composites
# ---------------------------------------------------------------------------

def scenario_authorized_wo(shop_overrides=None, entry_overrides=None, defect_overrides=None,
                           part=None, planned_parts=None, routing="SHOP", car_number="1001",
                           clock=BASE_CLOCK_ISO) -> dict:
    """Shop + parties + price entry + car + completed inspection + DRAFT WO
    with one line + submit + authorize. Returns the context dict."""
    ctx = setup_shop_ctx(clock=clock, shop_overrides=shop_overrides)
    add_price_entry(ctx, **(entry_overrides or {}))
    if part is not None:
        add_part(ctx, key="part", **part)
    add_car_with_inspection(ctx, car_number=car_number,
                            defects=[defect_overrides or DEFECT_AIR_HOSE])
    planned = planned_parts
    if planned is None and part is not None:
        planned = [{"part_item_id": ctx["parts"]["part"]["id"], "quantity": 1}]
    job_code = (entry_overrides or {}).get("job_code", ENTRY_AIR_HOSE["job_code"])
    build_work_order(ctx, routing=routing, lines=[{"job_code": job_code, "planned_parts": planned}])
    submit_current_wo(ctx)
    authorize_current_wo(ctx)
    return ctx


def scenario_completed_wo(actual_hours=1.5, shop_overrides=None, entry_overrides=None,
                          defect_overrides=None, part=None, planned_parts=None,
                          parts_used=None, routing="SHOP", car_number="1001",
                          slot_kwargs=None, clock=BASE_CLOCK_ISO) -> dict:
    """Full pipeline through QA PASS. Returns the context dict."""
    ctx = scenario_authorized_wo(shop_overrides=shop_overrides, entry_overrides=entry_overrides,
                                 defect_overrides=defect_overrides, part=part,
                                 planned_parts=planned_parts, routing=routing,
                                 car_number=car_number, clock=clock)
    if parts_used is None and part is not None:
        parts_used = [[{"part_item_id": ctx["parts"]["part"]["id"], "quantity": 1}]]
    run_wo_to_completed(ctx, routing=routing, actual_hours=actual_hours,
                        parts_used=parts_used, slot_kwargs=slot_kwargs)
    return ctx


def scenario_submitted_brc(**kwargs) -> dict:
    """Completed work order + BRC created and submitted. Returns the context dict."""
    ctx = scenario_completed_wo(**kwargs)
    create_brc_for_current_wo(ctx)
    submit_current_brc(ctx)
    return ctx
