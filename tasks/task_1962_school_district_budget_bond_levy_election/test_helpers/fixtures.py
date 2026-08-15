"""Composite setup helpers for multi-step test prerequisites.

All helpers build preconditions from scratch using only PRD-declared endpoints
(the harness restarts the server before every test, so each test starts against
an empty database). Setup calls use get_success_data() so failures surface as
clear "Setup step failed" errors instead of confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    ADOPTION_DAY_CLOCK, CANVASS_DAY_CLOCK, CERTIFY_SAFE_CLOCK, ELECTION_DATE,
    HEARING_DATE, HEARING_DAY_CLOCK, NOTICE_DATE, SALE_DATE, SALE_DAY_CLOCK,
)
from .factories import (
    amendment_adjustment, ballot_language_of_length, canvass_payload,
    canvass_result_entry, certify_projection_payload, create_amendment_payload,
    create_ballot_measure_payload, create_bond_project_payload,
    create_bond_proposal_payload, create_bond_sale_payload,
    create_budget_line_payload, create_budget_version_payload,
    create_election_payload, create_expenditure_payload,
    create_fiscal_year_payload, create_hearing_payload, create_position_payload,
    create_projection_payload, create_publication_payload,
    create_revenue_estimate_payload, create_staffing_allocation_payload,
    create_transfer_payload, fill_position_payload, review_payload,
    set_clock_payload,
)
from .test_users import (
    TEST_USERS, make_board_clerk_headers, make_budget_analyst_headers,
    make_superintendent_headers,
)

BA = TEST_USERS["budget_analyst_headers"]
BM = TEST_USERS["business_manager_headers"]
BC = TEST_USERS["board_clerk_headers"]
SU = TEST_USERS["superintendent_headers"]
DT = TEST_USERS["district_treasurer_headers"]
AU = TEST_USERS["auditor_headers"]

# Segregation-of-duties identity conventions (PRD §2.1: the server compares the
# X-User-ID values supplied by the two operators of a segregated pair).
DRAFTER_USER_ID = "clerk-drafter-1"
CERTIFIER_USER_ID = "clerk-certifier-2"
SUBMITTER_USER_ID = "analyst-7"
APPROVER_USER_ID = "supt-9"


# ─── Tier 0: clock ───────────────────────────────────────────────────────────

def set_clock(to_iso8601, headers=BM):
    """Set the server-side logical clock (PRD §2.5). Returns the clock data."""
    return get_success_data(
        api_client.set_clock(set_clock_payload(to_iso8601), headers))


# ─── Tier 1: single-resource creation ────────────────────────────────────────

def create_fiscal_year(**overrides):
    """Create a fiscal year (starts DRAFT). Returns the fiscal year."""
    return get_success_data(
        api_client.create_fiscal_year(create_fiscal_year_payload(**overrides),
                                      BM), 201)


def create_open_fiscal_year(**overrides):
    """Create + open a fiscal year (DRAFT -> OPEN). Returns the opened year."""
    fy = create_fiscal_year(**overrides)
    return get_success_data(api_client.open_fiscal_year(fy["id"], BM))


def get_fiscal_year(fy_id):
    return get_success_data(api_client.get_fiscal_year(fy_id, AU))


def add_projection(fy_id, grade_band="ELEMENTARY", projected_pupils=1200):
    """File one enrollment projection (PROVISIONAL). Returns the projection."""
    return get_success_data(api_client.create_enrollment_projection(
        fy_id, create_projection_payload(grade_band, projected_pupils), BA), 201)


def certify_projection(ep_id, actual_pupils):
    """Certify a projection with actual pupils (PROVISIONAL -> CERTIFIED)."""
    return get_success_data(api_client.certify_enrollment_projection(
        ep_id, certify_projection_payload(actual_pupils), BM))


def create_budget_version(fy_id):
    """Create a budget version against the fiscal year's CURRENT version
    (OCC token re-read fresh). Returns the new DRAFT budget version."""
    fy = get_fiscal_year(fy_id)
    return get_success_data(api_client.create_budget_version(
        fy_id, create_budget_version_payload(fy["version"]), BA), 201)


def add_budget_line(bv_id, appropriation_amount=1000, fund_code="EDUCATION",
                    function_code="1100", object_code="100",
                    cost_center="DISTRICT"):
    """Add an appropriation line to a DRAFT budget version."""
    return get_success_data(api_client.create_budget_line(
        bv_id,
        create_budget_line_payload(fund_code, function_code, object_code,
                                   cost_center, appropriation_amount),
        BA), 201)


def add_revenue_estimate(bv_id, **overrides):
    """Attach the (single) revenue estimate to a budget version."""
    return get_success_data(api_client.create_revenue_estimate(
        bv_id, create_revenue_estimate_payload(**overrides), BM), 201)


def add_staffing_allocation(bv_id, grade_band, enrollment_projection_id,
                            allocated_fte):
    """Create a staffing allocation on a DRAFT budget version."""
    return get_success_data(api_client.create_staffing_allocation(
        bv_id,
        create_staffing_allocation_payload(grade_band,
                                           enrollment_projection_id,
                                           allocated_fte),
        BA), 201)


def add_position(sa_id, title="Teacher 1", fte=1.0, base_salary=64000):
    """Slot a position under an allocation."""
    return get_success_data(api_client.create_position(
        sa_id, create_position_payload(title, fte, base_salary), BA), 201)


def propose(bv_id):
    return get_success_data(api_client.propose_budget_version(bv_id, BC))


def return_to_draft(bv_id):
    return get_success_data(
        api_client.return_budget_version_to_draft(bv_id, BC))


def adopt(bv_id):
    return get_success_data(api_client.adopt_budget_version(bv_id, BC))


def create_hearing(bv_id, venue="BOARD_ROOM", hearing_date=HEARING_DATE):
    """Publish notice and schedule a hearing for a PROPOSED version."""
    return get_success_data(api_client.create_hearing(
        bv_id, create_hearing_payload(venue, hearing_date), BC), 201)


def hold_hearing(h_id):
    return get_success_data(api_client.hold_hearing(h_id, BC))


def cancel_hearing(h_id):
    return get_success_data(api_client.cancel_hearing(h_id, BC))


def create_election(election_date=ELECTION_DATE, election_type="REGULAR"):
    return get_success_data(api_client.create_election(
        create_election_payload(election_date, election_type), BC), 201)


def create_bond_proposal(fy_id, total_amount=18000000,
                         question_title="Bond Question A",
                         purpose="Capital improvements"):
    return get_success_data(api_client.create_bond_proposal(
        fy_id, create_bond_proposal_payload(question_title, purpose,
                                            total_amount),
        BC), 201)


def add_project(bp_id, name="Roof Replacement", site_code="HS-01",
                estimated_cost=6000000, construction_start="2028-06-01",
                construction_end="2028-08-15", priority_rank=1):
    return get_success_data(api_client.create_bond_project(
        bp_id,
        create_bond_project_payload(name, site_code, estimated_cost,
                                    construction_start, construction_end,
                                    priority_rank),
        BC), 201)


def approve_board(bp_id):
    return get_success_data(api_client.approve_bond_proposal_board(bp_id, BC))


def create_ballot_measure(el_id, bp_id,
                          ballot_language="Shall the District issue bonds for "
                                          "capital improvements",
                          drafter_user_id=DRAFTER_USER_ID):
    """Draft a ballot measure; the drafting operator is recorded as
    drafted_by_user_id (PRD §3.7)."""
    return get_success_data(api_client.create_ballot_measure(
        el_id, create_ballot_measure_payload(bp_id, ballot_language),
        make_board_clerk_headers(drafter_user_id)), 201)


def certify_measure(bm_id, certifier_user_id=CERTIFIER_USER_ID):
    """Certify ballot language with a certifier distinct from the drafter."""
    return get_success_data(api_client.certify_ballot_measure(
        bm_id, make_board_clerk_headers(certifier_user_id)))


def canvass(el_id, results):
    return get_success_data(api_client.canvass_election(
        el_id, canvass_payload(results), BC))


def get_bond_proposal(bp_id):
    return get_success_data(api_client.get_bond_proposal(bp_id, AU))


def create_bond_sale(bp_id, series_label="2027-A", par_amount=10000000,
                     premium=150000, issuance_costs=80000, sale_date=SALE_DATE):
    """Plan a bond sale against the proposal's CURRENT version (OCC token
    re-read fresh). Returns the PLANNED sale."""
    bp = get_bond_proposal(bp_id)
    return get_success_data(api_client.create_bond_sale(
        bp_id,
        create_bond_sale_payload(series_label, par_amount, premium,
                                 issuance_costs, sale_date,
                                 expected_bond_proposal_version=bp["version"]),
        DT), 201)


def close_sale(bs_id):
    return get_success_data(api_client.close_bond_sale(bs_id, DT))


def activate_project(prj_id):
    return get_success_data(api_client.activate_bond_project(prj_id, SU))


def create_expenditure(prj_id, amount=1000000, vendor_name="Roofing Co",
                       description="roof tear-off"):
    return get_success_data(api_client.create_expenditure(
        prj_id, create_expenditure_payload(vendor_name, amount, description),
        DT), 201)


def create_amendment(bp_id, adjustments, reason="Reallocate between projects"):
    return get_success_data(api_client.create_amendment(
        bp_id, create_amendment_payload(reason, adjustments), BA), 201)


def submit_amendment(ca_id, submitter_user_id=SUBMITTER_USER_ID):
    return get_success_data(api_client.submit_amendment(
        ca_id, make_budget_analyst_headers(submitter_user_id)))


def approve_amendment(ca_id, approver_user_id=APPROVER_USER_ID):
    return get_success_data(api_client.approve_amendment(
        ca_id, make_superintendent_headers(approver_user_id)))


# ─── Tier 2: budget-side composites ──────────────────────────────────────────

DEFAULT_PUPILS = {"ELEMENTARY": 1200, "MIDDLE": 800, "HIGH": 1000}


def setup_fy_with_projections(pupils_by_band=None, fy_overrides=None):
    """OPEN fiscal year with one projection per requested band.
    Returns (fy, {band: projection})."""
    fy = create_open_fiscal_year(**(fy_overrides or {}))
    projections = {}
    for band, pupils in (pupils_by_band or {"ELEMENTARY": 1200}).items():
        projections[band] = add_projection(fy["id"], band, pupils)
    return fy, projections


def setup_draft_budget(pupils_by_band=None, line_amounts=(1000,),
                       with_revenue_estimate=True, fy_overrides=None,
                       estimate_overrides=None, allocation_specs=None,
                       position_specs=None):
    """OPEN fiscal year + projections + DRAFT budget version carrying the
    given lines and (optionally) its revenue estimate.

    allocation_specs: list of (grade_band, allocated_fte) — one allocation per
        band, computed from that band's projection.
    position_specs: list of (grade_band, title, fte, base_salary) — positions
        slotted under the allocation for that band.
    Returns dict(fy, projections, bv, re, allocations, positions)."""
    fy, projections = setup_fy_with_projections(pupils_by_band, fy_overrides)
    bv = create_budget_version(fy["id"])
    for amount in line_amounts:
        add_budget_line(bv["id"], appropriation_amount=amount)
    re = None
    if with_revenue_estimate:
        re = add_revenue_estimate(bv["id"], **(estimate_overrides or {}))
    allocations = {}
    for band, fte in (allocation_specs or []):
        allocations[band] = add_staffing_allocation(
            bv["id"], band, projections[band]["id"], fte)
    positions = []
    for band, title, fte, salary in (position_specs or []):
        positions.append(add_position(allocations[band]["id"], title, fte,
                                      salary))
    return {"fy": fy, "projections": projections, "bv": bv, "re": re,
            "allocations": allocations, "positions": positions}


def setup_proposed_budget(**kwargs):
    """DRAFT budget walked to PROPOSED."""
    ctx = setup_draft_budget(**kwargs)
    ctx["bv"] = propose(ctx["bv"]["id"])
    return ctx


def setup_hearing_held_budget(hearing_date=HEARING_DATE, venue="BOARD_ROOM",
                              **kwargs):
    """PROPOSED budget with a hearing HELD on hearing_date; the clock is left
    at the hearing day. Adds 'hearing' to the context."""
    ctx = setup_proposed_budget(**kwargs)
    set_clock(f"{NOTICE_DATE}T00:00:00Z", BC)
    hearing = create_hearing(ctx["bv"]["id"], venue, hearing_date)
    set_clock(f"{hearing_date}T09:00:00Z", BC)
    ctx["hearing"] = hold_hearing(hearing["id"])
    ctx["bv"] = get_success_data(
        api_client.get_budget_version(ctx["bv"]["id"], AU))
    return ctx


def setup_adopted_budget(hearing_date=HEARING_DATE, **kwargs):
    """Full lifecycle through ADOPTED: hearing held on hearing_date, then
    adopted at hearing_date + 7 days (before the fiscal year's start_date).
    The clock is left at the adoption day."""
    ctx = setup_hearing_held_budget(hearing_date=hearing_date, **kwargs)
    from datetime import date, timedelta
    held = date.fromisoformat(hearing_date)
    adopt_day = held + timedelta(days=7)
    set_clock(f"{adopt_day.isoformat()}T09:00:00Z", BC)
    ctx["bv"] = adopt(ctx["bv"]["id"])
    return ctx


# ─── Tier 3: bond-side composites ────────────────────────────────────────────

DEFAULT_PROJECTS = [
    # (name, site_code, estimated_cost, construction_start, construction_end)
    ("Roof Replacement", "HS-01", 6000000, "2028-06-01", "2028-08-15"),
]


def setup_approved_proposal(total_amount=18000000, projects=None,
                            fy_overrides=None):
    """OPEN fiscal year + DRAFT proposal with the project list, walked to
    BOARD_APPROVED. Returns dict(fy, bp, projects)."""
    fy = create_open_fiscal_year(**(fy_overrides or {}))
    bp = create_bond_proposal(fy["id"], total_amount=total_amount)
    created = []
    for i, spec in enumerate(projects or DEFAULT_PROJECTS):
        name, site, cost, start, end = spec
        created.append(add_project(bp["id"], name, site, cost, start, end,
                                   priority_rank=i + 1))
    bp = approve_board(bp["id"])
    return {"fy": fy, "bp": bp, "projects": created}


def setup_certified_measure(total_amount=18000000, projects=None,
                            election_date=ELECTION_DATE,
                            ballot_language=None,
                            fy_overrides=None):
    """BOARD_APPROVED proposal referred to an election via a certified ballot
    measure (proposal REFERRED). The clock is left at CERTIFY_SAFE_CLOCK.
    Adds 'el' and 'bm' to the context."""
    ctx = setup_approved_proposal(total_amount, projects, fy_overrides)
    el = create_election(election_date)
    bm = create_ballot_measure(el["id"], ctx["bp"]["id"],
                               ballot_language or
                               "Shall the District issue bonds for capital "
                               "improvements")
    set_clock(CERTIFY_SAFE_CLOCK, BC)
    bm = certify_measure(bm["id"])
    ctx.update({"el": el, "bm": bm})
    ctx["bp"] = get_bond_proposal(ctx["bp"]["id"])
    return ctx


def setup_passed_proposal(yes_votes=5200, no_votes=4800, **kwargs):
    """Full electoral path through canvass: the measure passes (default
    5200/4800), the proposal is PASSED, and its projects are AUTHORIZED.
    The clock is left at the canvass day."""
    ctx = setup_certified_measure(**kwargs)
    set_clock(CANVASS_DAY_CLOCK, BC)
    canvass(ctx["el"]["id"], [canvass_result_entry(ctx["bm"]["id"],
                                                  yes_votes, no_votes)])
    ctx["bm"] = get_success_data(
        api_client.get_ballot_measure(ctx["bm"]["id"], AU))
    ctx["bp"] = get_bond_proposal(ctx["bp"]["id"])
    return ctx


def setup_closed_sale(par_amount=10000000, premium=150000, issuance_costs=80000,
                      sale_date=SALE_DATE, series_label="2027-A", **kwargs):
    """PASSED proposal + one sale CLOSED on its sale date.
    Adds 'sale' to the context; net proceeds = par + premium - costs."""
    ctx = setup_passed_proposal(**kwargs)
    sale = create_bond_sale(ctx["bp"]["id"], series_label, par_amount,
                            premium, issuance_costs, sale_date)
    set_clock(f"{sale_date}T12:00:00Z", DT)
    ctx["sale"] = close_sale(sale["id"])
    ctx["bp"] = get_bond_proposal(ctx["bp"]["id"])
    return ctx


def setup_project_in_progress(**kwargs):
    """PASSED proposal + CLOSED sale + first project activated
    (AUTHORIZED -> IN_PROGRESS)."""
    ctx = setup_closed_sale(**kwargs)
    prj = ctx["projects"][0]
    activate_project(prj["id"])
    ctx["projects"][0] = get_success_data(
        api_client.get_bond_project(prj["id"], AU))
    return ctx


def setup_submitted_amendment(adjustments, submitter_user_id=SUBMITTER_USER_ID,
                              **kwargs):
    """PASSED proposal + amendment drafted and SUBMITTED by
    submitter_user_id. Adds 'ca' to the context."""
    ctx = setup_passed_proposal(**kwargs)
    ca = create_amendment(ctx["bp"]["id"], adjustments)
    ca = submit_amendment(ca["id"], submitter_user_id)
    ctx["ca"] = ca
    return ctx


__all__ = [name for name in dir() if not name.startswith("_")]
