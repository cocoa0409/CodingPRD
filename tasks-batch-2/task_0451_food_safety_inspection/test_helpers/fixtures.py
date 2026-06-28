"""Composite setup helpers for multi-step test prerequisites (Food Safety Inspection API).

Most interesting test claims require the system to be walked through many steps
(set clock -> create establishment -> plan review -> approve -> issue permit ->
schedule inspection -> start -> record violations -> complete -> finalize) before
the behavior under test is reachable. These helpers encapsulate those preambles.

All helpers use get_success_data() (the lenient 2xx validator) for setup calls so a
broken precondition surfaces as a clear "Setup failed" error rather than a confusing
assertion failure downstream. The harness restarts the server (empty DB) before every
test, so each helper builds its preconditions from scratch using PRD-declared endpoints.

Identity threading (PRD §2.1): the Inspector role is entity-backed. Every ownership-gated
inspector call here uses make_inspector_headers(inspector_id), never the shared constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_fda_food_code_payload,
    create_inspector_payload,
    create_establishment_payload,
    create_plan_review_payload,
    create_permit_payload,
    create_inspection_route_payload,
    create_inspection_payload,
    create_violation_payload,
    create_closure_order_payload,
    create_complaint_payload,
    create_enforcement_case_payload,
)
from .test_users import TEST_USERS, make_inspector_headers


CLERK = TEST_USERS["permit_clerk_headers"]
DIRECTOR = TEST_USERS["health_director_headers"]
OFFICER = TEST_USERS["enforcement_officer_headers"]


# ─── Clock control ────────────────────────────────────────────────────────
def set_clock(index: int):
    """Move the logical clock to an integer day index. Returns current_index."""
    data = get_success_data(api_client.set_clock(index, DIRECTOR))
    return data["current_index"]


def read_clock():
    """Read the current logical clock index without mutating it."""
    return get_success_data(api_client.get_clock(DIRECTOR))["current_index"]


# ─── Tier 1: Catalog & roster building blocks ───────────────────────────────
def create_code(classification="CRITICAL", base_demerit_points=10, code="3-501.16",
                title="Cold holding", **overrides):
    """Create an FdaFoodCode. Returns the created code row."""
    payload = create_fda_food_code_payload(
        code=code, title=title, classification=classification,
        base_demerit_points=base_demerit_points, **overrides)
    return get_success_data(api_client.create_fda_food_code(payload, DIRECTOR))


def retire_code(code_id):
    """Retire an FdaFoodCode. Returns the updated code row."""
    return get_success_data(api_client.retire_fda_food_code(code_id, DIRECTOR))


def create_inspector(full_name="Ivy One", badge_number="B-001", **overrides):
    """Register an Inspector. Returns the created inspector row."""
    payload = create_inspector_payload(full_name=full_name, badge_number=badge_number, **overrides)
    return get_success_data(api_client.create_inspector(payload, DIRECTOR))


# ─── Tier 1/2: Establishment lifecycle ──────────────────────────────────────
def create_establishment(**overrides):
    """Create a PRELICENSE establishment. Returns the created row."""
    payload = create_establishment_payload(**overrides)
    return get_success_data(api_client.create_establishment(payload, CLERK))


def create_establishment_with_approved_plan(plan_overrides=None, **est_overrides):
    """Create establishment + a SUBMITTED plan review + approve it (still PRELICENSE).

    Returns (establishment, plan_review).
    """
    est = create_establishment(**est_overrides)
    pr_payload = create_plan_review_payload(est["id"], **(plan_overrides or {}))
    pr = get_success_data(api_client.create_plan_review(pr_payload, CLERK))
    pr = get_success_data(api_client.approve_plan_review(pr["id"], CLERK))
    return est, pr


def create_permitted_establishment(plan_overrides=None, **est_overrides):
    """Walk establishment PRELICENSE -> PERMITTED via plan review + permit issuance.

    Returns (establishment, plan_review, permit). The returned establishment dict is
    re-fetched so its status reflects PERMITTED.
    """
    est, pr = create_establishment_with_approved_plan(plan_overrides=plan_overrides, **est_overrides)
    permit = get_success_data(api_client.create_permit(
        create_permit_payload(est["id"], pr["id"]), CLERK))
    est = get_success_data(api_client.get_establishment(est["id"], CLERK))
    return est, pr, permit


# ─── Tier 3: Inspection lifecycle shortcuts ─────────────────────────────────
def schedule_inspection(establishment_id, inspector_id, scheduled_index,
                        inspection_type="ROUTINE", **overrides):
    """Schedule a SCHEDULED inspection. Returns the created inspection row."""
    payload = create_inspection_payload(
        establishment_id, inspector_id, inspection_type, scheduled_index, **overrides)
    return get_success_data(api_client.create_inspection(payload, CLERK))


def start_inspection(inspection_id, inspector_id):
    """Drive a SCHEDULED inspection to IN_PROGRESS (ownership-gated)."""
    return get_success_data(api_client.start_inspection(inspection_id, make_inspector_headers(inspector_id)))


def add_violation(inspection_id, fda_code_id, inspector_id, corrected_on_site=False):
    """Record a violation on an editable inspection (ownership-gated). Returns the row."""
    payload = create_violation_payload(inspection_id, fda_code_id, corrected_on_site=corrected_on_site)
    return get_success_data(api_client.create_violation(payload, make_inspector_headers(inspector_id)))


def complete_inspection(inspection_id, inspector_id):
    """Drive an IN_PROGRESS or AMENDING inspection to COMPLETED. Returns the row."""
    return get_success_data(api_client.complete_inspection(inspection_id, make_inspector_headers(inspector_id)))


def finalize_inspection(inspection_id, inspector_id, expected_version):
    """Finalize a COMPLETED inspection with the supplied expected_inspection_version.

    Returns the finalized inspection row.
    """
    return get_success_data(api_client.finalize_inspection(
        inspection_id, {"expected_inspection_version": expected_version},
        make_inspector_headers(inspector_id)))


def setup_inspection_in_progress(scheduled_index=10, inspector=None, establishment=None):
    """Active establishment + inspector + a ROUTINE inspection driven to IN_PROGRESS.

    Returns (establishment, inspector, inspection). Reuses the supplied inspector /
    establishment if provided, else creates fresh ones.
    """
    insp = inspector or create_inspector()
    est = establishment
    if est is None:
        est, _, _ = create_permitted_establishment()
    inspection = schedule_inspection(est["id"], insp["id"], scheduled_index, "ROUTINE")
    start_inspection(inspection["id"], insp["id"])
    return est, insp, inspection


def setup_completed_inspection(scheduled_index=10, violations=None, inspector=None,
                               establishment=None):
    """Active establishment + inspector + a ROUTINE inspection driven to COMPLETED.

    `violations` is a list of (fda_code_id, corrected_on_site) tuples recorded while
    the inspection is editable. Returns (establishment, inspector, completed_inspection).
    """
    est, insp, inspection = setup_inspection_in_progress(
        scheduled_index=scheduled_index, inspector=inspector, establishment=establishment)
    for code_id, corrected in (violations or []):
        add_violation(inspection["id"], code_id, insp["id"], corrected_on_site=corrected)
    completed = complete_inspection(inspection["id"], insp["id"])
    return est, insp, completed


def setup_finalized_inspection(scheduled_index=10, violations=None, inspector=None,
                               establishment=None):
    """Full lifecycle through FINALIZED for a ROUTINE inspection.

    `violations` is a list of (fda_code_id, corrected_on_site) tuples. Returns
    (establishment, inspector, finalized_inspection). The finalized inspection is
    finalized using the COMPLETED version captured immediately before finalize.
    """
    est, insp, completed = setup_completed_inspection(
        scheduled_index=scheduled_index, violations=violations,
        inspector=inspector, establishment=establishment)
    finalized = finalize_inspection(completed["id"], insp["id"], completed["version"])
    return est, insp, finalized


# ─── Tier 4: Closure / suspension state targeting ───────────────────────────
def setup_suspended_via_closed_grade(scheduled_index=40, inspector=None, establishment=None):
    """Drive an establishment to SUSPENDED through a ROUTINE inspection that finalizes
    to a CLOSED grade via three uncorrected CRITICAL violations (critical_count 3).

    Returns (establishment, inspector, finalized_inspection, [code_ids]).
    """
    insp = inspector or create_inspector()
    est = establishment
    if est is None:
        est, _, _ = create_permitted_establishment()
    c1 = create_code("CRITICAL", 5, code="3-501.16", title="Cold holding")
    c2 = create_code("CRITICAL", 5, code="3-501.17", title="Date marking")
    c3 = create_code("CRITICAL", 5, code="3-302.11", title="Cross contamination")
    _, _, finalized = setup_finalized_inspection(
        scheduled_index=scheduled_index,
        violations=[(c1["id"], False), (c2["id"], False), (c3["id"], False)],
        inspector=insp, establishment=est)
    est = get_success_data(api_client.get_establishment(est["id"], CLERK))
    return est, insp, finalized, [c1["id"], c2["id"], c3["id"]]


def issue_manual_closure(establishment_id, triggering_inspection_id,
                         reason_code="IMMINENT_HEALTH_HAZARD"):
    """Issue a manual closure order (suspends a PERMITTED establishment). Returns row."""
    payload = create_closure_order_payload(establishment_id, triggering_inspection_id, reason_code)
    return get_success_data(api_client.create_closure_order(payload, OFFICER))


def lift_closure(closure_order_id):
    """Lift an ACTIVE closure order (reinstates the establishment). Returns row."""
    return get_success_data(api_client.lift_closure_order(closure_order_id, OFFICER))


# ─── Tier 4: Routes ─────────────────────────────────────────────────────────
def create_route(inspector_id, route_date_index):
    """Create a PLANNED inspection route. Returns the row."""
    payload = create_inspection_route_payload(inspector_id, route_date_index)
    return get_success_data(api_client.create_inspection_route(payload, CLERK))


def setup_route_with_stops(num_stops, route_date_index, max_daily_route_stops=None,
                           scheduled_base=None):
    """Inspector + N PERMITTED establishments + a PLANNED route holding `num_stops`
    SCHEDULED inspections (one per establishment), all on the route.

    `max_daily_route_stops` sets the inspector's capacity. Inspection scheduled_index
    values start at `scheduled_base` (defaults to route_date_index) and increment so
    no two inspections collide on the same day for the inspector. Returns
    (inspector, route, [inspections]).
    """
    insp_overrides = {}
    if max_daily_route_stops is not None:
        insp_overrides["max_daily_route_stops"] = max_daily_route_stops
    inspector = create_inspector(**insp_overrides)
    route = create_route(inspector["id"], route_date_index)
    base = scheduled_base if scheduled_base is not None else route_date_index
    inspections = []
    for i in range(num_stops):
        est, _, _ = create_permitted_establishment(
            name=f"Diner E{i + 1}", address=f"{i + 1} Main St")
        inspection = schedule_inspection(
            est["id"], inspector["id"], base + i, "ROUTINE", route_id=route["id"])
        inspections.append(inspection)
    route = get_success_data(api_client.get_inspection_route(route["id"], CLERK))
    return inspector, route, inspections


# ─── Tier 4: Enforcement cases ──────────────────────────────────────────────
def open_enforcement_case(establishment_id, alleged_penalty_cents, **overrides):
    """Open an OPENED enforcement case. Returns the row."""
    payload = create_enforcement_case_payload(establishment_id, alleged_penalty_cents, **overrides)
    return get_success_data(api_client.create_enforcement_case(payload, OFFICER))


def setup_case_hearing_scheduled(alleged_penalty_cents=50000, hearing_index=25,
                                 open_index=20, establishment=None, closure_order_id=None):
    """PERMITTED establishment + an enforcement case scheduled for a hearing.

    Sets the clock to `open_index`, opens the case, schedules the hearing at
    `hearing_index`. Returns (establishment, case). Caller advances the clock to
    hearing_index before ruling.
    """
    set_clock(open_index)
    est = establishment
    if est is None:
        est, _, _ = create_permitted_establishment()
    case_overrides = {}
    if closure_order_id is not None:
        case_overrides["closure_order_id"] = closure_order_id
    case = open_enforcement_case(est["id"], alleged_penalty_cents, **case_overrides)
    case = get_success_data(api_client.schedule_hearing(
        case["id"], {"hearing_index": hearing_index}, OFFICER))
    return est, case


# ─── Tier 5: Complaint lifecycle ────────────────────────────────────────────
def create_complaint(establishment_id, complaint_type="SANITATION", **overrides):
    """File a RECEIVED complaint. Returns the row."""
    payload = create_complaint_payload(establishment_id, complaint_type, **overrides)
    return get_success_data(api_client.create_complaint(payload, CLERK))


def setup_dispatched_complaint(complaint_type="FOODBORNE_ILLNESS", reported_ill_count=3,
                               scheduled_index=80, inspector=None, establishment=None):
    """PERMITTED establishment + an inspector + a complaint TRIAGED then DISPATCHED,
    spawning a SCHEDULED COMPLAINT inspection.

    Returns (establishment, inspector, complaint). The complaint dict is re-fetched so
    its linked_inspection_id and DISPATCHED status are populated.
    """
    set_clock(scheduled_index)
    insp = inspector or create_inspector()
    est = establishment
    if est is None:
        est, _, _ = create_permitted_establishment()
    overrides = {}
    if reported_ill_count is not None:
        overrides["reported_ill_count"] = reported_ill_count
    complaint = create_complaint(est["id"], complaint_type, **overrides)
    get_success_data(api_client.triage_complaint(complaint["id"], CLERK))
    get_success_data(api_client.dispatch_complaint(
        complaint["id"], {"inspector_id": insp["id"]}, make_inspector_headers(insp["id"])))
    complaint = get_success_data(api_client.get_complaint(complaint["id"], CLERK))
    return est, insp, complaint
