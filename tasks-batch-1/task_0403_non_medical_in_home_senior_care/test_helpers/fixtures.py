"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints, because the server database is empty at the start of each test.
Helpers use get_success_data() (lenient) so setup failures surface clearly.

Caregiver-owned calls (clock-in, clock-out, depart, mileage) thread the real
Caregiver.id through make_caregiver_headers() per PRD section 2.1.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS, make_caregiver_headers,
)

ADMIN = TEST_USERS["agency_admin_headers"]
SCHEDULER = TEST_USERS["scheduler_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
def set_clock(to_iso8601):
    """Pin the server clock (PRD section 2.12). Admin-only."""
    return api_client.set_clock(to_iso8601, ADMIN)


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation + state progression
# ---------------------------------------------------------------------------
def create_agency(**overrides):
    payload = {
        "name": "A",
        "base_hourly_rate": 30.00,
        "live_in_day_rate": 250.00,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_agency(payload, ADMIN))


def create_caregiver(agency_id, **overrides):
    payload = {
        "agency_id": agency_id,
        "full_name": "CG",
        "hire_state_code": "CA",
    }
    payload.update(overrides)
    return get_success_data(api_client.create_caregiver(payload, ADMIN))


def create_active_caregiver(agency_id, target_tier="TIER_1", **overrides):
    """Register -> CLEAR_BACKGROUND -> ACTIVATE. Returns the ACTIVE caregiver."""
    cg = create_caregiver(agency_id, **overrides)
    get_success_data(api_client.transition_caregiver(
        cg["id"], {"action": "CLEAR_BACKGROUND", "target_tier": target_tier}, ADMIN))
    data = get_success_data(api_client.transition_caregiver(
        cg["id"], {"action": "ACTIVATE"}, ADMIN))
    return data


def create_client(agency_id, **overrides):
    payload = {
        "agency_id": agency_id,
        "full_name": "CL",
        "residence_state_code": "CA",
    }
    payload.update(overrides)
    return get_success_data(api_client.create_client(payload, ADMIN))


def create_active_client(agency_id, **overrides):
    """Create -> ACTIVATE (INTAKE -> ACTIVE). Returns the ACTIVE client."""
    cl = create_client(agency_id, **overrides)
    return get_success_data(api_client.transition_client(
        cl["id"], {"action": "ACTIVATE"}, SCHEDULER))


def create_published_plan(client_id, title="Plan"):
    """Create a care plan and PUBLISH it. Returns the PUBLISHED plan."""
    plan = get_success_data(api_client.create_care_plan(
        client_id, {"title": title}, SCHEDULER))
    return get_success_data(api_client.transition_care_plan(
        plan["id"], {"action": "PUBLISH"}, SCHEDULER))


def create_active_match(caregiver_id, client_id, is_primary=True):
    """Propose + ACTIVATE a match. Returns the ACTIVE match."""
    payload = {"caregiver_id": caregiver_id, "client_id": client_id,
               "is_primary": is_primary}
    match = get_success_data(api_client.create_match(payload, SCHEDULER))
    return get_success_data(api_client.transition_match(
        match["id"], {"action": "ACTIVATE"}, SCHEDULER))


# ---------------------------------------------------------------------------
# Tier 2: a ready-to-clock scenario (active everything + one scheduled visit)
# ---------------------------------------------------------------------------
def setup_schedulable_scenario(target_tier="TIER_1", caregiver_overrides=None,
                               client_overrides=None):
    """Active agency/caregiver/client + published plan + active primary match.

    Returns dict with keys: agency, caregiver, client, plan, match (all dicts).
    """
    agency = create_agency()
    cg = create_active_caregiver(agency["id"], target_tier=target_tier,
                                 **(caregiver_overrides or {}))
    cl = create_active_client(agency["id"], **(client_overrides or {}))
    plan = create_published_plan(cl["id"])
    match = create_active_match(cg["id"], cl["id"], is_primary=True)
    return {"agency": agency, "caregiver": cg, "client": cl,
            "plan": plan, "match": match}


def schedule_visit(caregiver_id, client_id, care_plan_id,
                   scheduled_start, scheduled_end, billing_mode="HOURLY"):
    payload = {
        "caregiver_id": caregiver_id,
        "client_id": client_id,
        "care_plan_id": care_plan_id,
        "billing_mode": billing_mode,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    return get_success_data(api_client.create_visit(payload, SCHEDULER))


def clock_in_visit(visit_id, caregiver_id, event_at, **extra):
    payload = {"event_at": event_at}
    payload.update(extra)
    return get_success_data(api_client.clock_in(
        visit_id, payload, make_caregiver_headers(caregiver_id)))


def clock_out_visit(visit_id, caregiver_id, event_at, **extra):
    payload = {"event_at": event_at}
    payload.update(extra)
    return get_success_data(api_client.clock_out(
        visit_id, payload, make_caregiver_headers(caregiver_id)))


def create_completed_visit(caregiver_id, client_id, care_plan_id,
                           scheduled_start, scheduled_end,
                           clock_in_at, clock_out_at, billing_mode="HOURLY"):
    """Schedule -> clock-in -> clock-out. Returns the COMPLETED visit."""
    v = schedule_visit(caregiver_id, client_id, care_plan_id,
                       scheduled_start, scheduled_end, billing_mode)
    clock_in_visit(v["id"], caregiver_id, clock_in_at)
    return clock_out_visit(v["id"], caregiver_id, clock_out_at)


def create_in_progress_visit(caregiver_id, client_id, care_plan_id,
                             scheduled_start, scheduled_end, clock_in_at,
                             billing_mode="HOURLY"):
    """Schedule -> clock-in. Returns the IN_PROGRESS visit."""
    v = schedule_visit(caregiver_id, client_id, care_plan_id,
                       scheduled_start, scheduled_end, billing_mode)
    return clock_in_visit(v["id"], caregiver_id, clock_in_at)


# ---------------------------------------------------------------------------
# Tier 3: invoices
# ---------------------------------------------------------------------------
def open_invoice(agency_id, caregiver_id, client_id, period_start, period_end):
    payload = {
        "agency_id": agency_id,
        "caregiver_id": caregiver_id,
        "client_id": client_id,
        "period_start": period_start,
        "period_end": period_end,
    }
    return get_success_data(api_client.create_invoice(payload, BILLING))


def finalize_invoice(invoice_id):
    return get_success_data(api_client.finalize_invoice(invoice_id, BILLING))


def setup_issued_invoice_single_visit():
    """Active scenario + one COMPLETED 8h HOURLY visit (invoice_total 240.00)
    + an ISSUED invoice covering [2026-06-01, 2026-06-08).

    Returns dict: agency, caregiver, client, plan, match, visit, invoice.
    invoice is the ISSUED snapshot (its `version` reflects the post-finalize value).
    """
    set_clock("2026-06-01T07:00:00Z")
    s = setup_schedulable_scenario()
    cg, cl, plan = s["caregiver"], s["client"], s["plan"]
    visit = create_completed_visit(
        cg["id"], cl["id"], plan["id"],
        "2026-06-01T09:00:00Z", "2026-06-01T17:00:00Z",
        "2026-06-01T09:00:00Z", "2026-06-01T17:00:00Z")
    inv = open_invoice(s["agency"]["id"], cg["id"], cl["id"],
                       "2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z")
    issued = finalize_invoice(inv["id"])
    s.update({"visit": visit, "invoice": issued})
    return s


def setup_six_visit_overtime_invoice(finalize=False):
    """Active scenario + six COMPLETED HOURLY visits (five 8h, one 6h = 46h)
    in ISO week 23, and a DRAFT invoice over [2026-06-01, 2026-06-08).

    Provisional charges sum to 1380.00; final labor_total (with overtime past
    40h) is 1470.00.

    Returns dict: agency, caregiver, client, plan, match, visits (list of 6),
    invoice (DRAFT, or ISSUED if finalize=True).
    """
    set_clock("2026-06-01T07:00:00Z")
    s = setup_schedulable_scenario(target_tier="TIER_2",
                                   caregiver_overrides={"max_weekly_hours": 50})
    cg, cl, plan = s["caregiver"], s["client"], s["plan"]
    windows = [
        ("2026-06-01T09:00:00Z", "2026-06-01T17:00:00Z"),  # 8h
        ("2026-06-02T09:00:00Z", "2026-06-02T17:00:00Z"),  # 8h
        ("2026-06-03T09:00:00Z", "2026-06-03T17:00:00Z"),  # 8h
        ("2026-06-04T09:00:00Z", "2026-06-04T17:00:00Z"),  # 8h
        ("2026-06-05T09:00:00Z", "2026-06-05T17:00:00Z"),  # 8h
        ("2026-06-06T09:00:00Z", "2026-06-06T15:00:00Z"),  # 6h
    ]
    visits = []
    for start, end in windows:
        v = create_completed_visit(cg["id"], cl["id"], plan["id"],
                                   start, end, start, end)
        visits.append(v)
    inv = open_invoice(s["agency"]["id"], cg["id"], cl["id"],
                       "2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z")
    if finalize:
        inv = finalize_invoice(inv["id"])
    s.update({"visits": visits, "invoice": inv})
    return s


# ---------------------------------------------------------------------------
# Tier 4: claims on issued invoices
# ---------------------------------------------------------------------------
def assign_claim(client_id, invoice_id, expected_invoice_version,
                 insurer_name="Ins", policy_number="P1", covered_pct=0.50,
                 daily_benefit_max=500, covered_days=5):
    payload = {
        "client_id": client_id,
        "invoice_id": invoice_id,
        "insurer_name": insurer_name,
        "policy_number": policy_number,
        "covered_pct": covered_pct,
        "daily_benefit_max": daily_benefit_max,
        "covered_days": covered_days,
        "expected_invoice_version": expected_invoice_version,
    }
    return get_success_data(api_client.create_claim(payload, BILLING))


def submit_claim(claim_id):
    return get_success_data(api_client.submit_claim(claim_id, BILLING))


def get_invoice(invoice_id):
    return get_success_data(api_client.get_invoice(invoice_id, BILLING))


def setup_submitted_claim(covered_pct=0.50, daily_benefit_max=500,
                          covered_days=5):
    """ISSUED invoice (total 240.00) + a SUBMITTED claim.

    Returns dict: agency, caregiver, client, plan, match, visit, invoice
    (ISSUED snapshot), claim (SUBMITTED snapshot).
    """
    s = setup_issued_invoice_single_visit()
    inv = s["invoice"]
    claim = assign_claim(s["client"]["id"], inv["id"], inv["version"],
                         covered_pct=covered_pct,
                         daily_benefit_max=daily_benefit_max,
                         covered_days=covered_days)
    submitted = submit_claim(claim["id"])
    s["claim"] = submitted
    return s
