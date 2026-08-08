"""Composite setup helpers.

Each test starts against an empty database (the runner restarts the server
before every test), so every helper builds its preconditions from scratch
using only PRD-declared endpoints. All setup calls use get_success_data()
so a broken precondition surfaces as a clear "Setup failed".
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS
from .factories import (
    create_district_payload,
    create_liaison_payload,
    create_student_payload,
    create_determination_payload,
    create_plan_payload,
    create_cost_share_payload,
    create_vehicle_payload,
    create_trip_payload,
)

SC = TEST_USERS["state_coordinator_headers"]


# ---------------------------------------------------------------------------
# Tier 1 — single-entity creators
# ---------------------------------------------------------------------------
def create_district(budget=100_000_000, name="D1", nces_code="0601", headers=None) -> dict:
    resp = api_client.create_district(
        create_district_payload(name=name, nces_code=nces_code, transport_budget_cents=budget),
        headers or SC,
    )
    return get_success_data(resp)


def create_liaison(district_id, max_caseload=None, headers=None) -> dict:
    overrides = {}
    if max_caseload is not None:
        overrides["max_caseload"] = max_caseload
    resp = api_client.create_liaison(create_liaison_payload(district_id, **overrides), headers or SC)
    return get_success_data(resp)


def create_student(district_id, living_situation="SHELTER", origin_district_id=None,
                   headers=None, **overrides) -> dict:
    resp = api_client.create_student(
        create_student_payload(district_id, origin_district_id=origin_district_id,
                               living_situation=living_situation, **overrides),
        headers or SC,
    )
    return get_success_data(resp)


def create_vehicle(district_id, label="Bus1", headers=None) -> dict:
    resp = api_client.create_vehicle(create_vehicle_payload(district_id, label=label), headers or SC)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2 — eligibility
# ---------------------------------------------------------------------------
def make_student_eligible(student_id, student_version, category="HOMELESS",
                          basis="SHELTER", decision="ELIGIBLE") -> dict:
    """Create a determination for the student and finalize it.

    Returns the finalized determination data. On ELIGIBLE this fires the
    depth-3 cascade (eligibility_status, BenefitLink, district count).
    """
    det = get_success_data(api_client.create_determination(
        student_id,
        create_determination_payload(student_version, category=category, basis=basis, decision=decision),
        SC,
    ))
    finalized = get_success_data(api_client.finalize_determination(det["id"], SC))
    return finalized


def setup_eligible_student(living_situation="SHELTER", basis="SHELTER",
                           category="HOMELESS", district=None, budget=100_000_000) -> dict:
    """District + student made ELIGIBLE via a finalized determination.

    Returns {district, student (refetched), determination}.
    """
    d = district or create_district(budget=budget)
    s = create_student(d["id"], living_situation=living_situation)
    det = make_student_eligible(s["id"], s["version"], category=category, basis=basis, decision="ELIGIBLE")
    student = get_success_data(api_client.get_student(s["id"], SC))
    return {"district": d, "student": student, "determination": det}


# ---------------------------------------------------------------------------
# Tier 3 — plan lifecycle
# ---------------------------------------------------------------------------
def create_plan(student_id, district_id, route_miles=20, origin_district_id=None, headers=None) -> dict:
    resp = api_client.create_plan(
        create_plan_payload(student_id, origin_district_id or district_id, district_id, route_miles=route_miles),
        headers or SC,
    )
    return get_success_data(resp)


def create_cost_share(plan_id, plan_version, headers=None) -> dict:
    resp = api_client.create_cost_share(create_cost_share_payload(plan_id, plan_version), headers or SC)
    return get_success_data(resp)


def setup_plan_with_cost_share(route_miles=20, budget=100_000_000, base=None) -> dict:
    """Eligible student + DRAFT plan + cost-share agreement.

    Returns {district, student, determination, plan, agreement}.
    """
    base = base or setup_eligible_student(budget=budget)
    plan = create_plan(base["student"]["id"], base["district"]["id"], route_miles=route_miles)
    agreement = create_cost_share(plan["id"], plan["version"])
    return {**base, "plan": plan, "agreement": agreement}


def setup_approved_plan(route_miles=20, budget=100_000_000, base=None) -> dict:
    """Eligible student, plan submitted+approved (with cost-share). Plan is APPROVED."""
    ctx = setup_plan_with_cost_share(route_miles=route_miles, budget=budget, base=base)
    api_client.submit_plan(ctx["plan"]["id"], SC)
    api_client.approve_plan(ctx["plan"]["id"], SC)
    ctx["plan"] = get_success_data(api_client.get_plan(ctx["plan"]["id"], SC))
    return ctx


def setup_active_plan(route_miles=20, budget=100_000_000, base=None) -> dict:
    """Eligible student, plan taken all the way to ACTIVE.

    Returns {district, student, determination, plan (ACTIVE, refetched), agreement}.
    """
    ctx = setup_approved_plan(route_miles=route_miles, budget=budget, base=base)
    api_client.activate_plan(ctx["plan"]["id"], SC)
    ctx["plan"] = get_success_data(api_client.get_plan(ctx["plan"]["id"], SC))
    return ctx


def setup_active_plan_with_vehicle(route_miles=20, budget=100_000_000, base=None) -> dict:
    """ACTIVE plan plus one IN_SERVICE vehicle in the serving district.

    Returns the setup_active_plan dict plus {vehicle}.
    """
    ctx = setup_active_plan(route_miles=route_miles, budget=budget, base=base)
    ctx["vehicle"] = create_vehicle(ctx["district"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 4 — trips
# ---------------------------------------------------------------------------
def create_trip(plan_id, vehicle_id, scheduled_start, scheduled_end, headers=None) -> dict:
    resp = api_client.create_trip(
        create_trip_payload(plan_id, vehicle_id, scheduled_start, scheduled_end),
        headers or SC,
    )
    return get_success_data(resp)


def create_completed_trip(plan_id, vehicle_id, scheduled_start, scheduled_end, actual_miles=20) -> dict:
    trip = create_trip(plan_id, vehicle_id, scheduled_start, scheduled_end)
    completed = get_success_data(api_client.complete_trip(trip["id"], {"actual_miles": actual_miles}, SC))
    return completed


def setup_completed_trip(route_miles=20, actual_miles=20,
                         start="2026-05-04T08:00:00Z", end="2026-05-04T08:30:00Z") -> dict:
    """ACTIVE plan + vehicle + one COMPLETED trip. Returns ctx plus {trip}."""
    ctx = setup_active_plan_with_vehicle(route_miles=route_miles)
    ctx["trip"] = create_completed_trip(ctx["plan"]["id"], ctx["vehicle"]["id"], start, end, actual_miles=actual_miles)
    return ctx


# ---------------------------------------------------------------------------
# Tier 5 — disputes
# ---------------------------------------------------------------------------
def create_dispute(student_id, dispute_type="ELIGIBILITY", description="Contest.", headers=None) -> dict:
    from .factories import create_dispute_payload
    resp = api_client.create_dispute(
        create_dispute_payload(student_id, dispute_type=dispute_type, description=description),
        headers or SC,
    )
    return get_success_data(resp)


def setup_dispute_under_review(student_id=None, dispute_type="ELIGIBILITY") -> dict:
    """A dispute for a (fresh if not given) student, advanced to UNDER_REVIEW.

    Returns {district, student, dispute}.
    """
    if student_id is None:
        d = create_district()
        s = create_student(d["id"])
        student_id = s["id"]
        out = {"district": d, "student": s}
    else:
        out = {}
    dsp = create_dispute(student_id, dispute_type=dispute_type)
    api_client.begin_review(dsp["id"], SC)
    out["dispute"] = get_success_data(api_client.get_dispute(dsp["id"], SC))
    return out
