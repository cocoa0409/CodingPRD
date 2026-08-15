"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so each helper builds its preconditions from scratch using
only PRD-declared endpoints. Setup calls use get_success_data() so a failed
precondition surfaces as a clear setup error rather than an assertion failure.

Canonical fixture (mirrors the figures documented in constants.py):
  jurisdiction deadline 21d / dispute window 30d / interest 300bp ACTUAL_DAYS /
  stale 180d / cap 1,000,000c / multiplier x2 / lock allowed / actual-cost off;
  property fees key 5,000c / fob 7,500c / lock 12,000c;
  unit carpet 2022-08-01 (5y) / paint 2025-08-01 (3y);
  tenancy lease 2025-01-10..2026-08-10, deposit 200,000c, keys 2, fobs 1;
  clock 2025-01-10 at move-in completion, 2026-08-01 at move-out completion.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_ISSUE_TIMELY,
    CLOCK_MOVE_IN,
    CLOCK_MOVE_OUT,
)
from .factories import (
    DEFAULTS,
    create_disbursement_payload,
    create_deduction_payload,
    create_dispute_payload,
    create_inspection_item_payload,
    create_inspection_payload,
    create_jurisdiction_profile_payload,
    create_property_payload,
    create_statement_payload,
    create_tenancy_payload,
    create_unit_payload,
)
from .test_users import (
    make_inspector_headers,
    make_manager_admin_headers,
    make_property_manager_headers,
    make_tenant_headers,
)

ADMIN = make_manager_admin_headers()
PM = make_property_manager_headers()
INSP = make_inspector_headers()


# ---------------------------------------------------------------------------
# Tier 1/2: configuration hierarchy
# ---------------------------------------------------------------------------

def create_jurisdiction(**overrides):
    """Create a jurisdiction profile. Returns the profile dict."""
    resp = api_client.create_jurisdiction_profile(
        create_jurisdiction_profile_payload(**overrides), ADMIN
    )
    return get_success_data(resp)


def create_property(jurisdiction_profile_id, **overrides):
    resp = api_client.create_property(
        create_property_payload(jurisdiction_profile_id=jurisdiction_profile_id, **overrides),
        ADMIN,
    )
    return get_success_data(resp)


def create_unit(property_id, **overrides):
    resp = api_client.create_unit(
        create_unit_payload(property_id=property_id, **overrides), ADMIN
    )
    return get_success_data(resp)


def setup_portfolio(unit_count=1, jurisdiction_overrides=None, unit_overrides=None,
                    unit_overrides_list=None):
    """Jurisdiction + property + N units.

    unit_overrides_list, when given, is a list of per-unit override dicts.
    Returns (jurisdiction, property, [units...]).
    """
    jur = create_jurisdiction(**(jurisdiction_overrides or {}))
    prop = create_property(jur["id"])
    units = []
    for i in range(unit_count):
        ov = dict(unit_overrides or {})
        if unit_overrides_list:
            ov.update(unit_overrides_list[i])
        ov.setdefault("unit_number", f"1{chr(65 + i)}")
        units.append(create_unit(prop["id"], **ov))
    return jur, prop, units


# ---------------------------------------------------------------------------
# Tier 1: tenancy + inspection state progression
# ---------------------------------------------------------------------------

def create_tenancy(unit_id, **overrides):
    resp = api_client.create_tenancy(
        create_tenancy_payload(unit_id=unit_id, **overrides), PM
    )
    return get_success_data(resp)


def schedule_inspection(tenancy_id, kind, **overrides):
    payload = create_inspection_payload(tenancy_id=tenancy_id, kind=kind, **overrides)
    resp = api_client.create_inspection(payload, PM)
    return get_success_data(resp)


def add_item(inspection_id, **overrides):
    resp = api_client.add_inspection_item(
        inspection_id, create_inspection_item_payload(**overrides), INSP
    )
    return get_success_data(resp)


def complete_inspection(inspection_id):
    resp = api_client.complete_inspection(inspection_id, INSP)
    return get_success_data(resp)


def setup_occupied_tenancy(unit_id=None, jurisdiction_overrides=None,
                           unit_overrides=None, tenancy_overrides=None,
                           move_in_item_overrides=None,
                           move_in_clock=CLOCK_MOVE_IN):
    """Portfolio + tenancy driven to OCCUPIED via a completed MOVE_IN inspection.

    Returns dict with keys: jur, prop, unit, tenancy, move_in (inspection),
    move_in_item (None when move_in_item_overrides is None and no item added —
    pass move_in_item_overrides={} to add a default item).
    """
    jur, prop, units = setup_portfolio(
        unit_count=1 if unit_id is None else 0,
        jurisdiction_overrides=jurisdiction_overrides,
        unit_overrides=unit_overrides,
    )
    unit = units[0] if unit_id is None else None
    tenancy = create_tenancy(unit_id or unit["id"], **(tenancy_overrides or {}))
    api_client.set_clock({"to_iso8601": move_in_clock}, ADMIN)
    mi = schedule_inspection(tenancy["id"], "MOVE_IN")
    mi_item = None
    if move_in_item_overrides is not None:
        mi_item = add_item(mi["id"], **move_in_item_overrides)
    complete_inspection(mi["id"])
    tenancy = get_success_data(api_client.get_tenancy(tenancy["id"], PM))
    return {"jur": jur, "prop": prop, "unit": unit, "tenancy": tenancy,
            "move_in": mi, "move_in_item": mi_item}


def setup_notice_given(unit_id=None, jurisdiction_overrides=None, unit_overrides=None,
                       tenancy_overrides=None, move_in_item_overrides=None,
                       keys_returned=None, fobs_returned=None,
                       notice_clock=CLOCK_MOVE_OUT):
    """OCCUPIED + give_notice (+ optional record_key_return). Returns ctx dict."""
    ctx = setup_occupied_tenancy(
        unit_id=unit_id,
        jurisdiction_overrides=jurisdiction_overrides,
        unit_overrides=unit_overrides,
        tenancy_overrides=tenancy_overrides,
        move_in_item_overrides=move_in_item_overrides,
    )
    api_client.set_clock({"to_iso8601": notice_clock}, ADMIN)
    ten = ctx["tenancy"]
    get_success_data(api_client.give_notice(ten["id"], PM))
    if keys_returned is not None or fobs_returned is not None:
        payload = {
            "keys_returned": keys_returned if keys_returned is not None else ten["keys_issued"],
            "fobs_returned": fobs_returned if fobs_returned is not None else ten["fobs_issued"],
        }
        get_success_data(api_client.record_key_return(ten["id"], payload, PM))
    ctx["tenancy"] = get_success_data(api_client.get_tenancy(ten["id"], PM))
    return ctx


def setup_vacated_tenancy(move_out_items=None, keys_returned=None, fobs_returned=None,
                          jurisdiction_overrides=None, unit_overrides=None,
                          tenancy_overrides=None, move_in_item_overrides=None,
                          move_in_clock=CLOCK_MOVE_IN, move_out_clock=CLOCK_MOVE_OUT,
                          link_move_in_item=True):
    """Full chain to VACATED with a completed MOVE_OUT inspection.

    move_out_items: list of item override dicts (defaults to one assessed
    PAINT TENANT_DAMAGE item with replacement 90,000c linked to the move-in
    paint item). Pass [] to complete with zero items.

    keys_returned / fobs_returned default to "everything handed back" (the
    issued counts) so the canonical VACATED tenancy carries no key/fob/lock
    lines; pass explicit counts to exercise the hardware-charge branch.

    Returns ctx dict with keys: jur, prop, unit, tenancy (VACATED), move_in,
    move_in_item, move_out, move_out_items (list of created item dicts),
    deductions (list of deduction dicts for the tenancy).
    """
    tenancy_overrides = tenancy_overrides or {}
    if keys_returned is None:
        keys_returned = tenancy_overrides.get("keys_issued", DEFAULTS["KEYS_ISSUED"])
    if fobs_returned is None:
        fobs_returned = tenancy_overrides.get("fobs_issued", DEFAULTS["FOBS_ISSUED"])
    if move_out_items is None:
        move_out_items = [{
            "area_name": "bedroom_paint",
            "category": "PAINT",
            "condition": "DAMAGED",
            "photo_count": 4,
            "determination": "TENANT_DAMAGE",
            "replacement_cost_cents": 90_000,
        }]
    if move_in_item_overrides is None and link_move_in_item and move_out_items:
        move_in_item_overrides = {}

    ctx = setup_notice_given(
        jurisdiction_overrides=jurisdiction_overrides,
        unit_overrides=unit_overrides,
        tenancy_overrides=tenancy_overrides,
        move_in_item_overrides=move_in_item_overrides,
        keys_returned=keys_returned,
        fobs_returned=fobs_returned,
        notice_clock=move_out_clock,
    )
    ten = ctx["tenancy"]
    mo = schedule_inspection(ten["id"], "MOVE_OUT",
                             scheduled_start_at="2026-08-01T10:00:00Z",
                             scheduled_end_at="2026-08-01T11:00:00Z")
    created_items = []
    for ov in move_out_items:
        ov = dict(ov)
        if link_move_in_item and ctx.get("move_in_item") is not None:
            ov.setdefault("linked_move_in_item_id", ctx["move_in_item"]["id"])
        created_items.append(add_item(mo["id"], **ov))
    complete_inspection(mo["id"])
    tenancy = get_success_data(api_client.get_tenancy(ten["id"], PM))
    deductions, _meta = _list_deductions(tenancy["id"])
    ctx.update({"tenancy": tenancy, "move_out": mo, "move_out_items": created_items,
                "deductions": deductions})
    return ctx


def _list_deductions(tenancy_id):
    resp = api_client.list_deductions(PM, params={"tenancy_id": tenancy_id, "limit": 100})
    data = get_success_data(resp)
    if isinstance(data, list):
        return data, None
    return data.get("data", data), None


def list_tenancy_deductions(tenancy_id):
    """All deduction lines of a tenancy (list endpoint, DRAFT + BILLED)."""
    rows, _ = _list_deductions(tenancy_id)
    return rows


# ---------------------------------------------------------------------------
# Tier 3: statement lifecycle shortcuts
# ---------------------------------------------------------------------------

def get_tenancy(tenancy_id):
    return get_success_data(api_client.get_tenancy(tenancy_id, PM))


def get_statement(statement_id):
    return get_success_data(api_client.get_statement(statement_id, PM))


def get_dispute(dispute_id):
    return get_success_data(api_client.get_dispute(dispute_id, PM))


def get_disbursement(disbursement_id):
    return get_success_data(api_client.get_disbursement(disbursement_id, PM))


def get_unit(unit_id):
    return get_success_data(api_client.get_unit(unit_id, PM))


def create_statement_for(tenancy_id):
    """Create a DRAFT statement using the tenancy's freshly observed version
    (OCC guard). Returns the statement dict."""
    ten = get_tenancy(tenancy_id)
    resp = api_client.create_statement(
        create_statement_payload(tenancy_id=tenancy_id,
                                 expected_tenancy_version=ten["version"]),
        PM,
    )
    return get_success_data(resp)


def setup_vacated_with_statement(issue_clock=None, **vacated_kwargs):
    """VACATED tenancy + DRAFT statement; issues the statement when
    issue_clock is given. Returns ctx with key 'statement'."""
    ctx = setup_vacated_tenancy(**vacated_kwargs)
    stmt = create_statement_for(ctx["tenancy"]["id"])
    if issue_clock is not None:
        api_client.set_clock({"to_iso8601": issue_clock}, ADMIN)
        get_success_data(api_client.issue_statement(stmt["id"], PM))
        stmt = get_statement(stmt["id"])
        ctx["tenancy"] = get_tenancy(ctx["tenancy"]["id"])
    ctx["statement"] = stmt
    return ctx


def setup_issued_statement_with_damage(**overrides):
    """Canonical issued timely statement: paint damage 60,000c, refund_due
    149,337c. Returns ctx."""
    return setup_vacated_with_statement(issue_clock=CLOCK_ISSUE_TIMELY, **overrides)


def setup_issued_with_cleaning(cleaning_amount=8_000, **overrides):
    """Canonical issued statement carrying an extra manual CLEANING line of
    8,000c (deduction_total 68,000c, refund_due 141,337c)."""
    ctx = setup_vacated_tenancy(**overrides)
    get_success_data(api_client.create_deduction(
        create_deduction_payload(tenancy_id=ctx["tenancy"]["id"],
                                 amount_cents=cleaning_amount), PM))
    stmt = create_statement_for(ctx["tenancy"]["id"])
    api_client.set_clock({"to_iso8601": CLOCK_ISSUE_TIMELY}, ADMIN)
    get_success_data(api_client.issue_statement(stmt["id"], PM))
    ctx["statement"] = get_statement(stmt["id"])
    ctx["tenancy"] = get_tenancy(ctx["tenancy"]["id"])
    return ctx


def setup_dispute_on_statement(ctx=None, disputed_amount=20_000, reason="paint was already worn",
                               **setup_kwargs):
    """Issued statement + OPEN dispute opened by the owning tenant.
    Returns ctx with keys 'statement' and 'dispute'."""
    if ctx is None:
        ctx = setup_issued_statement_with_damage(**setup_kwargs)
    stmt = ctx["statement"]
    ten = ctx["tenancy"]
    resp = api_client.create_dispute(
        create_dispute_payload(statement_id=stmt["id"],
                               disputed_amount_cents=disputed_amount,
                               reason=reason),
        make_tenant_headers(ten["id"]),
    )
    dispute = get_success_data(resp)
    ctx["dispute"] = dispute
    ctx["statement"] = get_statement(stmt["id"])
    return ctx


def setup_escalated_dispute(ctx=None, disputed_amount=20_000, **setup_kwargs):
    """Issued statement + dispute escalated to ESCALATED_SMALL_CLAIMS."""
    ctx = setup_dispute_on_statement(ctx=ctx, disputed_amount=disputed_amount, **setup_kwargs)
    ten = ctx["tenancy"]
    get_success_data(api_client.escalate_dispute(ctx["dispute"]["id"],
                                                 make_tenant_headers(ten["id"])))
    ctx["dispute"] = get_dispute(ctx["dispute"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: disbursement / settlement terminal states
# ---------------------------------------------------------------------------

def setup_refund_sent(ctx=None, amount=None, **setup_kwargs):
    """Issued statement + REFUND disbursement in SENT. Amount defaults to the
    statement's refund_due_cents. Returns ctx with key 'disbursement'."""
    if ctx is None:
        ctx = setup_issued_statement_with_damage(**setup_kwargs)
    stmt = ctx["statement"]
    if amount is None:
        amount = stmt["refund_due_cents"]
    resp = api_client.create_disbursement(
        create_disbursement_payload(tenancy_id=ctx["tenancy"]["id"],
                                    statement_id=stmt["id"],
                                    kind="REFUND",
                                    amount_cents=amount),
        PM,
    )
    ctx["disbursement"] = get_success_data(resp)
    ctx["tenancy"] = get_tenancy(ctx["tenancy"]["id"])
    return ctx


def setup_settled_tenancy(ctx=None, **setup_kwargs):
    """Full lifecycle to statement SETTLED + tenancy SETTLED: REFUND of the
    full refund_due created and marked cashed. Returns ctx."""
    ctx = setup_refund_sent(ctx=ctx, **setup_kwargs)
    get_success_data(api_client.mark_cashed(ctx["disbursement"]["id"], PM))
    ctx["disbursement"] = get_disbursement(ctx["disbursement"]["id"])
    ctx["statement"] = get_statement(ctx["statement"]["id"])
    ctx["tenancy"] = get_tenancy(ctx["tenancy"]["id"])
    return ctx
