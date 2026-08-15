"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before each test, so each test
starts against an empty database). Setup calls use get_success_data() so a
setup failure surfaces as a clear error, not a confusing assertion failure.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_START
from .factories import (
    create_application_payload,
    create_closure_payload,
    create_condition_payload,
    create_facility_payload,
    create_fee_schedule_payload,
    create_organization_payload,
    create_payment_payload,
    create_window_payload,
)
from .test_users import (
    TEST_USERS,
    make_finance_clerk_headers,
    make_org_coordinator_headers,
)

ADMIN = TEST_USERS["athletics_admin_headers"]
SUPERVISOR = TEST_USERS["field_supervisor_headers"]
CLERK = TEST_USERS["finance_clerk_headers"]


# ---------------------------------------------------------------------------
# Tier 0: logical clock + atomic creators
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str = CLOCK_START):
    """Drive the server's logical clock (AthleticsAdmin-only capability)."""
    res = api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    assert res.status_code == 200, f"clock setup failed: {res.status_code} {res.text}"


def create_organization(**overrides) -> dict:
    return get_success_data(api_client.create_organization(
        create_organization_payload(**overrides), ADMIN))


def create_facility(**overrides) -> dict:
    return get_success_data(api_client.create_facility(
        create_facility_payload(**overrides), ADMIN))


def create_fee_schedule(**overrides) -> dict:
    return get_success_data(api_client.create_fee_schedule(
        create_fee_schedule_payload(**overrides), ADMIN))


def publish_fee_schedule(schedule_id: str) -> dict:
    return get_success_data(api_client.publish_fee_schedule(schedule_id, ADMIN))


def create_allocation_window(**overrides) -> dict:
    return get_success_data(api_client.create_allocation_window(
        create_window_payload(**overrides), ADMIN))


def open_allocation_window(window_id: str) -> dict:
    return get_success_data(api_client.open_allocation_window(window_id, ADMIN))


def close_allocation_window(window_id: str) -> dict:
    return get_success_data(api_client.close_allocation_window(window_id, ADMIN))


def run_allocation(window_id: str) -> dict:
    return get_success_data(api_client.run_allocation(window_id, ADMIN))


def submit_application(window_id: str, facility_id: str, org_id: str, **overrides) -> dict:
    """Submit an application as the owning OrgCoordinator (X-User-ID is the
    Organization's id per PRD section 2.1)."""
    return get_success_data(api_client.create_permit_application(
        create_application_payload(window_id, facility_id, **overrides),
        make_org_coordinator_headers(org_id)))


def create_field_closure(facility_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_field_closure(
        create_closure_payload(facility_id, **overrides), SUPERVISOR))


def record_condition(facility_id: str, condition_status: str, reason: str) -> dict:
    """Record a condition decision with a freshly read facility version (OCC).
    The weekly-load recompute may or may not advance the facility version, so
    always re-read instead of trusting a previously captured version."""
    fresh = get_success_data(api_client.get_facility(facility_id, ADMIN))
    return get_success_data(api_client.record_facility_condition(
        facility_id,
        create_condition_payload(condition_status, reason, fresh["version"]),
        SUPERVISOR))


# ---------------------------------------------------------------------------
# Tier 1: lookups and simple transitions
# ---------------------------------------------------------------------------

def get_permit_for_application(application_id: str) -> dict:
    permits = get_success_data(api_client.list_permits(
        ADMIN, params={"application_id": application_id}))
    assert len(permits) == 1, f"expected exactly one permit for {application_id}, got {len(permits)}"
    return permits[0]


def get_invoice_for_permit(permit_id: str) -> dict:
    invoices = get_success_data(api_client.list_invoices(
        CLERK, params={"permit_id": permit_id}))
    assert len(invoices) == 1, f"expected exactly one invoice for {permit_id}, got {len(invoices)}"
    return invoices[0]


def get_usage_ledger(org_id: str, season_code: str) -> dict:
    ledgers = get_success_data(api_client.list_usage_ledgers(
        ADMIN, params={"organization_id": org_id, "season_code": season_code}))
    assert len(ledgers) == 1, f"expected exactly one ledger for {org_id}/{season_code}, got {len(ledgers)}"
    return ledgers[0]


def list_strikes(org_id: str, status: str = None) -> list:
    params = {"organization_id": org_id}
    if status is not None:
        params["status"] = status
    return get_success_data(api_client.list_strike_records(ADMIN, params=params))


def get_organization(org_id: str) -> dict:
    return get_success_data(api_client.get_organization(org_id, ADMIN))


def get_permit(permit_id: str) -> dict:
    return get_success_data(api_client.get_permit(permit_id, ADMIN))


def get_invoice(invoice_id: str) -> dict:
    return get_success_data(api_client.get_invoice(invoice_id, CLERK))


def get_facility(facility_id: str) -> dict:
    return get_success_data(api_client.get_facility(facility_id, ADMIN))


def get_application(application_id: str) -> dict:
    return get_success_data(api_client.get_permit_application(application_id, ADMIN))


def issue_invoice(invoice_id: str) -> dict:
    return get_success_data(api_client.issue_invoice(invoice_id, CLERK))


def pay_invoice(invoice_id: str, amount_cents: int, method: str = "CHECK",
                clerk_id: str = None) -> dict:
    headers = make_finance_clerk_headers(clerk_id) if clerk_id else CLERK
    return get_success_data(api_client.record_payment(
        invoice_id, create_payment_payload(amount_cents, method), headers))


def confirm_permit(permit_id: str, org_id: str) -> dict:
    return get_success_data(api_client.confirm_permit(
        permit_id, make_org_coordinator_headers(org_id)))


def cancel_permit_as_owner(permit_id: str, org_id: str):
    """Raw response: cancel as the owning coordinator."""
    return api_client.cancel_permit(permit_id, make_org_coordinator_headers(org_id))


def rain_out_permit(facility_id: str, closure_date: str, reason: str = "RAIN") -> dict:
    """Create a full-day closure on the facility/date, raining out every
    intersecting RESERVED/CONFIRMED permit. Returns the closure."""
    return create_field_closure(facility_id, closure_date=closure_date, reason=reason)


def mark_no_show_at(permit_id: str, clock_iso: str) -> dict:
    """Move the logical clock past the slot end and mark the permit no-show."""
    set_clock(clock_iso)
    return get_success_data(api_client.mark_no_show(permit_id, SUPERVISOR))


def reschedule_as_owner(permit_id: str, org_id: str, new_date: str,
                        new_start_minute: int, new_end_minute: int):
    """Raw response: reschedule with a freshly read permit version (OCC)."""
    fresh = get_permit(permit_id)
    return api_client.reschedule_permit(
        permit_id,
        {
            "new_date": new_date,
            "new_start_minute": new_start_minute,
            "new_end_minute": new_end_minute,
            "expected_permit_version": fresh["version"],
        },
        make_org_coordinator_headers(org_id))


# ---------------------------------------------------------------------------
# Tier 2/3: season composites
# ---------------------------------------------------------------------------

def setup_open_season(org_overrides=None, facility_overrides=None,
                      schedule_overrides=None, window_overrides=None,
                      publish_schedule=True, clock: str = CLOCK_START) -> dict:
    """Org + facility (+ published fee schedule) + an OPEN allocation window.

    Returns a context dict with organization, facility, schedule (or None),
    and window.
    """
    set_clock(clock)
    org = create_organization(**(org_overrides or {}))
    facility = create_facility(**(facility_overrides or {}))
    schedule = None
    if publish_schedule:
        schedule = publish_fee_schedule(
            create_fee_schedule(**(schedule_overrides or {}))["id"])
    window = create_allocation_window(**(window_overrides or {}))
    window = open_allocation_window(window["id"])
    return {"organization": org, "facility": facility,
            "schedule": schedule, "window": window}


def setup_awarded_permit(app_overrides=None, **season_kwargs) -> dict:
    """Open season + one application + close + allocation run.

    Returns the season context plus application, permit (RESERVED), and
    invoice (DRAFT).
    """
    ctx = setup_open_season(**season_kwargs)
    application = submit_application(
        ctx["window"]["id"], ctx["facility"]["id"], ctx["organization"]["id"],
        **(app_overrides or {}))
    close_allocation_window(ctx["window"]["id"])
    run_allocation(ctx["window"]["id"])
    ctx["application"] = get_application(application["id"])
    ctx["permit"] = get_permit_for_application(application["id"])
    ctx["invoice"] = get_invoice_for_permit(ctx["permit"]["id"])
    return ctx


def setup_confirmed_permit(app_overrides=None, pay_cents=None, **season_kwargs) -> dict:
    """Awarded permit taken through confirmation: invoice ISSUED, a cleared
    payment covering the deposit, permit CONFIRMED."""
    ctx = setup_awarded_permit(app_overrides, **season_kwargs)
    issue_invoice(ctx["invoice"]["id"])
    invoice = get_invoice(ctx["invoice"]["id"])
    pay_invoice(invoice["id"], pay_cents if pay_cents is not None else invoice["deposit_cents"])
    ctx["permit"] = confirm_permit(ctx["permit"]["id"], ctx["organization"]["id"])
    ctx["invoice"] = get_invoice(invoice["id"])
    return ctx


def setup_rained_out_permit(closure_overrides=None, **kwargs) -> dict:
    """Confirmed permit rained out by a full-day closure on its slot date.
    The context's permit is refreshed (post-cascade version) for OCC use."""
    ctx = setup_confirmed_permit(**kwargs)
    closure = rain_out_permit(
        ctx["facility"]["id"],
        closure_date=ctx["permit"]["permit_date"],
        **(closure_overrides or {}))
    ctx["closure"] = closure
    ctx["permit"] = get_permit(ctx["permit"]["id"])
    ctx["invoice"] = get_invoice(ctx["invoice"]["id"])
    return ctx


def record_no_shows(ctx: dict, count: int, start: int = 0) -> None:
    """Mark `count` permits of the context as no-shows, beginning at
    ctx["permits"][start], moving the logical clock past each slot's end
    (slots end at 16:00 on their dates)."""
    for i in range(start, start + count):
        permit = ctx["permits"][i]
        mark_no_show_at(permit["id"], f"{permit['permit_date']}T17:00:00Z")


def setup_suspended_org(**kwargs) -> dict:
    """Org driven to SUSPENDED via three sequential no-shows. The fourth
    permit (2026-08-15, after the third no-show's clock) is revoked by the
    suspension cascade. Returns the four-permit context."""
    ctx = setup_org_with_confirmed_permits(**kwargs)
    record_no_shows(ctx, 3)
    return ctx


def setup_late_strike_scenario() -> dict:
    """Two-window strike-timing scenario for the provisional/final score split.

    Window W1 (closes 2026-08-03) awards the org a CONFIRMED permit for
    2026-08-05 18:00-20:00 (2h, no lights; quote 4000, deposit 4000, paid).
    Window W2 (closes 2026-08-08) is opened and the org's second application
    (2026-08-12 18:00-20:00) is submitted at 2026-08-04T12:00 — while the org
    has zero active strikes, so the provisional snapshot is strike-free.
    The W1 permit is then marked no-show at 2026-08-05T21:00, landing one
    strike between submission and W2's allocation run.

    Returns a dict with organization, facility, schedule, w1, p1, i1, w2, a2,
    and a2_provisional (the provisional score captured at submission).
    """
    set_clock()
    org = create_organization()
    facility = create_facility()
    schedule = publish_fee_schedule(create_fee_schedule()["id"])

    w1 = create_allocation_window(closes_at="2026-08-03T23:59:59Z")
    open_allocation_window(w1["id"])
    a1 = submit_application(w1["id"], facility["id"], org["id"],
                            event_date="2026-08-05")
    close_allocation_window(w1["id"])
    run_allocation(w1["id"])
    p1 = get_permit_for_application(a1["id"])
    i1 = get_invoice_for_permit(p1["id"])
    issue_invoice(i1["id"])
    i1 = get_invoice(i1["id"])
    pay_invoice(i1["id"], i1["deposit_cents"])
    p1 = confirm_permit(p1["id"], org["id"])

    w2 = create_allocation_window(closes_at="2026-08-08T23:59:59Z")
    open_allocation_window(w2["id"])
    set_clock("2026-08-04T12:00:00Z")
    a2 = submit_application(w2["id"], facility["id"], org["id"],
                            event_date="2026-08-12")

    set_clock("2026-08-05T21:00:00Z")
    get_success_data(api_client.mark_no_show(p1["id"], SUPERVISOR))

    return {"organization": org, "facility": facility, "schedule": schedule,
            "w1": w1, "p1": p1, "i1": i1, "w2": w2, "a2": a2,
            "a2_provisional": a2["provisional_score"]}


def setup_org_with_confirmed_permits(dates=("2026-08-06", "2026-08-07",
                                            "2026-08-08", "2026-08-15"),
                                     start_minute=840, end_minute=960,
                                     window_closes_at="2026-08-04T23:59:59Z",
                                     **season_kwargs) -> dict:
    """One organization holding one CONFIRMED permit per date in `dates`.

    Each slot is a daytime non-prime LEAGUE_PRACTICE (2h, no lights); every
    invoice is issued and paid in full (quote equals deposit at these sizes),
    then the permit is confirmed. Returns the season context plus parallel
    lists applications / permits / invoices aligned with `dates`.
    """
    window_overrides = dict(season_kwargs.pop("window_overrides", {}) or {})
    window_overrides.setdefault("closes_at", window_closes_at)
    ctx = setup_open_season(window_overrides=window_overrides, **season_kwargs)
    org_id = ctx["organization"]["id"]
    ctx["applications"] = []
    for i, date in enumerate(dates):
        # Nudge the logical clock so created_at order matches submission order
        # regardless of which clock the server stamps creations with.
        set_clock(f"2026-08-01T09:{i:02d}:00Z")
        ctx["applications"].append(submit_application(
            ctx["window"]["id"], ctx["facility"]["id"], org_id,
            event_date=date, start_minute=start_minute, end_minute=end_minute,
            event_type="LEAGUE_PRACTICE", wants_lights=False, headcount=30))
    close_allocation_window(ctx["window"]["id"])
    run_allocation(ctx["window"]["id"])
    ctx["permits"], ctx["invoices"] = [], []
    for application in ctx["applications"]:
        permit = get_permit_for_application(application["id"])
        invoice = get_invoice_for_permit(permit["id"])
        issue_invoice(invoice["id"])
        invoice = get_invoice(invoice["id"])
        pay_invoice(invoice["id"], invoice["deposit_cents"])
        permit = confirm_permit(permit["id"], org_id)
        ctx["permits"].append(permit)
        ctx["invoices"].append(get_invoice(invoice["id"]))
    return ctx
