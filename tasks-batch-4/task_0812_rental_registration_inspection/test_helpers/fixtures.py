"""Composite setup helpers.

Every helper builds its preconditions from scratch (the server DB is empty at the
start of every test) using only PRD-declared endpoints, and uses get_success_data()
so setup failures surface as clear "Setup failed" errors. Ownership-gated calls
thread the real entity id through make_landlord_headers()/make_inspector_headers().
"""
from prd_bench_local_runner.testing import get_success_data
from .test_users import (
    TEST_USERS, make_landlord_headers, make_inspector_headers,
)
from .factories import (
    create_landlord_payload, create_inspector_payload, create_property_payload,
    create_inspection_payload, create_checklist_item_payload, create_license_payload,
    create_complaint_payload, create_notice_payload, create_condemnation_order_payload,
)

REGISTRAR = TEST_USERS["registrar_headers"]
TENANT = TEST_USERS["tenant_headers"]

DEFAULT_CLOCK = "2026-06-01T09:00:00Z"


# --- Atomic helpers ------------------------------------------------------

def set_clock(api, iso: str):
    return get_success_data(api.set_clock(iso, REGISTRAR))


def create_landlord(api, **overrides) -> dict:
    return get_success_data(api.create_landlord(create_landlord_payload(**overrides), REGISTRAR))


def create_inspector(api, **overrides) -> dict:
    return get_success_data(api.create_inspector(create_inspector_payload(**overrides), REGISTRAR))


def create_property(api, landlord_id, **overrides) -> dict:
    headers = make_landlord_headers(landlord_id)
    return get_success_data(
        api.create_property(create_property_payload(landlord_id, **overrides), headers))


def get_property(api, property_id) -> dict:
    return get_success_data(api.get_property(property_id, REGISTRAR))


def schedule_inspection(api, property_id, inspector_id, scheduled_date, **overrides) -> dict:
    headers = make_inspector_headers(inspector_id)
    payload = create_inspection_payload(property_id, inspector_id, scheduled_date, **overrides)
    return get_success_data(api.create_inspection(payload, headers))


def record_item(api, inspection_id, inspector_id, category, code, result, **overrides) -> dict:
    headers = make_inspector_headers(inspector_id)
    payload = create_checklist_item_payload(category, code, result, **overrides)
    return get_success_data(api.create_checklist_item(inspection_id, payload, headers))


def begin_inspection(api, inspection_id, inspector_id) -> dict:
    return get_success_data(api.begin_inspection(inspection_id, make_inspector_headers(inspector_id)))


def complete_inspection(api, inspection_id, inspector_id) -> dict:
    return get_success_data(api.complete_inspection(inspection_id, make_inspector_headers(inspector_id)))


# --- Tier 1/2: baseline participants + property --------------------------

def setup_landlord_inspector_property(api, clock=DEFAULT_CLOCK, **prop_overrides) -> dict:
    """Registrar seeds a landlord + inspector; landlord registers a REGISTERED property.
    Returns dict(landlord, inspector, property, property_id, landlord_id, inspector_id)."""
    set_clock(api, clock)
    landlord = create_landlord(api)
    inspector = create_inspector(api)
    prop = create_property(api, landlord["id"], **prop_overrides)
    return {
        "landlord": landlord,
        "inspector": inspector,
        "property": prop,
        "landlord_id": landlord["id"],
        "inspector_id": inspector["id"],
        "property_id": prop["id"],
    }


# --- Tier 3: run a periodic inspection to a terminal result --------------

def run_periodic_to_passed(api, ctx, scheduled_date=None) -> dict:
    """Schedule + begin + record two passing mandatory-category items + complete → PASSED.
    Mutates/returns ctx with 'passed_inspection'. Property has a PASSED PERIODIC inspection."""
    sd = scheduled_date or DEFAULT_CLOCK
    insp = schedule_inspection(api, ctx["property_id"], ctx["inspector_id"], sd,
                               inspection_type="PERIODIC")
    begin_inspection(api, insp["id"], ctx["inspector_id"])
    record_item(api, insp["id"], ctx["inspector_id"], "LIFE_SAFETY", "SMOKE_DETECTOR", "PASS")
    record_item(api, insp["id"], ctx["inspector_id"], "HABITABILITY", "HEAT", "PASS")
    completed = complete_inspection(api, insp["id"], ctx["inspector_id"])
    ctx["passed_inspection"] = completed
    return ctx


def run_periodic_with_fail_items(api, ctx, fail_items, pass_items=None, scheduled_date=None) -> dict:
    """Schedule + begin + record the given FAIL items (list of dicts with category/code/severity)
    plus optional PASS items + complete. Used to reach FAILED and mint violations.
    Returns ctx with 'inspection' and 'violations' (violations of that inspection)."""
    sd = scheduled_date or DEFAULT_CLOCK
    insp = schedule_inspection(api, ctx["property_id"], ctx["inspector_id"], sd,
                               inspection_type="PERIODIC")
    begin_inspection(api, insp["id"], ctx["inspector_id"])
    for item in (pass_items or []):
        record_item(api, insp["id"], ctx["inspector_id"], item["category"], item["code"], "PASS")
    for item in fail_items:
        record_item(api, insp["id"], ctx["inspector_id"], item["category"], item["code"],
                    "FAIL", severity=item.get("severity", "MINOR"))
    completed = complete_inspection(api, insp["id"], ctx["inspector_id"])
    ctx["inspection"] = completed
    violations, _ = _list_violations_for_inspection(api, insp["id"])
    ctx["violations"] = violations
    return ctx


def _list_violations_for_inspection(api, inspection_id):
    resp = api.list_violations(REGISTRAR, params={"inspection_id": inspection_id})
    data = get_success_data(resp)
    # data is the array payload for list endpoints
    return data, resp


# --- Tier 3: licensing ---------------------------------------------------

def issue_license(api, property_id, term_years=1) -> dict:
    """Registrar issues a PENDING_PAYMENT license (OCC using the property's current version)."""
    prop = get_property(api, property_id)
    payload = create_license_payload(property_id, prop["version"], term_years=term_years)
    return get_success_data(api.create_license(payload, REGISTRAR))


def create_active_license(api, ctx, term_years=1, amount_cents=None) -> dict:
    """Requires ctx already has a PASSED periodic inspection and no open critical violations.
    Issue → pay → ACTIVE. Returns the ACTIVE license dict; stores in ctx['license']."""
    lic = issue_license(api, ctx["property_id"], term_years=term_years)
    pay_amount = amount_cents if amount_cents is not None else lic["fee_cents"]
    paid = get_success_data(
        api.pay_license(lic["id"], {"amount_cents": pay_amount},
                        make_landlord_headers(ctx["landlord_id"])))
    ctx["license"] = paid
    return paid


def setup_property_with_active_license(api, clock=DEFAULT_CLOCK, term_years=1, **prop_overrides) -> dict:
    """Full path: landlord + inspector + property + PASSED periodic + issued + paid ACTIVE license.
    Returns ctx with landlord/inspector/property/passed_inspection/license."""
    ctx = setup_landlord_inspector_property(api, clock=clock, **prop_overrides)
    run_periodic_to_passed(api, ctx)
    create_active_license(api, ctx, term_years=term_years)
    return ctx


def setup_property_with_pending_license(api, clock=DEFAULT_CLOCK, run_inspection=True, **prop_overrides) -> dict:
    """landlord + inspector + property (+ optional PASSED periodic) + a PENDING_PAYMENT license.
    Returns ctx with 'license' (PENDING_PAYMENT)."""
    ctx = setup_landlord_inspector_property(api, clock=clock, **prop_overrides)
    if run_inspection:
        run_periodic_to_passed(api, ctx)
    ctx["license"] = issue_license(api, ctx["property_id"])
    return ctx


# --- Tier 4: violations at controlled states -----------------------------

def setup_property_with_violations(api, fail_items, clock=DEFAULT_CLOCK,
                                   pass_items=None, **prop_overrides) -> dict:
    """Property + a FAILED periodic inspection that mints one violation per FAIL item.
    Returns ctx with 'violations' list (ordered as returned)."""
    ctx = setup_landlord_inspector_property(api, clock=clock, **prop_overrides)
    run_periodic_with_fail_items(api, ctx, fail_items, pass_items=pass_items)
    return ctx


def list_property_violations(api, property_id, **params):
    p = {"property_id": property_id}
    p.update(params)
    return get_success_data(api.list_violations(REGISTRAR, params=p))


# --- Tier: notices, complaints, condemnation -----------------------------

def create_notice(api, property_id, **overrides) -> dict:
    return get_success_data(api.create_notice(create_notice_payload(property_id, **overrides), REGISTRAR))


def create_complaint(api, property_id, **overrides) -> dict:
    return get_success_data(api.create_complaint(create_complaint_payload(property_id, **overrides), TENANT))


def create_condemnation_order(api, property_id, **overrides) -> dict:
    return get_success_data(
        api.create_condemnation_order(create_condemnation_order_payload(property_id, **overrides), REGISTRAR))


def list_property_notices(api, property_id, **params):
    return get_success_data(api.list_property_notices(property_id, REGISTRAR, params=params or None))
