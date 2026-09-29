"""Composite setup helpers.

Every helper builds its state from scratch through PRD-declared endpoints: the
server is restarted before each test, so nothing is ever carried over.

Identity threading is mandatory here. A `ClinicalRequester` call is issued with
the acting department's `id`, a `FacilityDirector` call with the acting
facility's `id` and a `CommitteeMember` call with the acting member's `id`.
Allocation runs use one planner identity and funding uses another, because the
identity recorded on the allocation is barred from funding.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_START
from .factories import (
    allocate_payload,
    collect_audit_payload,
    create_asset_payload,
    create_audit_payload,
    create_cycle_payload,
    create_department_payload,
    create_facility_payload,
    create_gpo_contract_payload,
    create_member_payload,
    create_project_payload,
    create_quote_payload,
    create_request_payload,
    create_service_event_payload,
    decommission_payload,
    screen_payload,
    set_clock_payload,
    vote_payload,
)
from .test_users import (
    TEST_USERS,
    make_clinical_requester_headers,
    make_committee_member_headers,
    make_facility_director_headers,
)

PLANNER = TEST_USERS["planner_headers"]
PLANNER_ALLOC = TEST_USERS["planner_alloc_headers"]
PLANNER_FUND = TEST_USERS["planner_fund_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# ─── Tier 0: single-call helpers ──────────────────────────────────────


def pin_clock(now: str = CLOCK_START) -> dict:
    return get_success_data(api_client.set_clock(set_clock_payload(now), PLANNER))


def make_facility(**overrides) -> dict:
    return get_success_data(
        api_client.create_facility(create_facility_payload(**overrides), PLANNER)
    )


def make_department(facility_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_department(create_department_payload(facility_id, **overrides), PLANNER)
    )


def make_asset(facility_id: str, department_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_asset(
            create_asset_payload(facility_id, department_id, **overrides), PLANNER
        )
    )


def add_service_event(asset_id: str, event_date: str, category: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_service_event(
            asset_id, create_service_event_payload(event_date, category, **overrides), PLANNER
        )
    )


def make_cycle(**overrides) -> dict:
    return get_success_data(api_client.create_cycle(create_cycle_payload(**overrides), PLANNER))


def open_intake(cycle_id: str) -> dict:
    return get_success_data(api_client.open_intake(cycle_id, PLANNER))


def close_intake(cycle_id: str) -> dict:
    return get_success_data(api_client.close_intake(cycle_id, PLANNER))


def run_scoring(cycle_id: str) -> dict:
    return get_success_data(api_client.score_cycle(cycle_id, PLANNER))


def run_allocation(cycle_id: str, allocation_method: str = "PRO_RATA",
                   expected_cycle_version: int = None, headers: dict = None) -> dict:
    """Run the facility allocation. Reads the cycle's current version when none is given."""
    if expected_cycle_version is None:
        expected_cycle_version = refresh_cycle(cycle_id)["version"]
    return get_success_data(
        api_client.allocate_cycle(
            cycle_id,
            allocate_payload(allocation_method, expected_cycle_version),
            headers or PLANNER_ALLOC,
        )
    )


def commit_cycle(cycle_id: str) -> dict:
    return get_success_data(api_client.commit_cycle(cycle_id, PLANNER))


def make_request(cycle_id: str, department_id: str, asset_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_request(
            create_request_payload(cycle_id, department_id, asset_id, **overrides),
            make_clinical_requester_headers(department_id),
        )
    )


def submit(request_id: str, department_id: str) -> dict:
    return get_success_data(
        api_client.submit_request(request_id, make_clinical_requester_headers(department_id))
    )


def screen(request_id: str, decision: str = "ACCEPT", **overrides) -> dict:
    return get_success_data(
        api_client.screen_request(request_id, screen_payload(decision, **overrides), PLANNER)
    )


def withdraw(request_id: str, department_id: str, **payload) -> dict:
    return get_success_data(
        api_client.withdraw_request(
            request_id, make_clinical_requester_headers(department_id), payload or None
        )
    )


def make_member(seat: str, voting_weight: int, **overrides) -> dict:
    return get_success_data(
        api_client.create_committee_member(
            create_member_payload(seat, voting_weight, **overrides), PLANNER
        )
    )


def cast_vote(request_id: str, member_id: str, vote: str,
              expected_request_version: int = None, **overrides) -> dict:
    """Cast a ballot. Reads the request's current version when none is given."""
    if expected_request_version is None:
        expected_request_version = refresh_request(request_id)["version"]
    return get_success_data(
        api_client.create_vote(
            request_id,
            vote_payload(vote, expected_request_version, **overrides),
            make_committee_member_headers(member_id),
        )
    )


def close_voting(request_id: str, chair_member_id: str, **payload) -> dict:
    return get_success_data(
        api_client.committee_decision(
            request_id, make_committee_member_headers(chair_member_id), payload or None
        )
    )


def fund(request_id: str, headers: dict = None) -> dict:
    return get_success_data(api_client.fund_request(request_id, headers or PLANNER_FUND))


def withdraw_funding(request_id: str, headers: dict = None, **payload) -> dict:
    return get_success_data(
        api_client.withdraw_funding(request_id, headers or PLANNER_FUND, payload or None)
    )


def make_gpo_contract(**overrides) -> dict:
    return get_success_data(
        api_client.create_gpo_contract(create_gpo_contract_payload(**overrides), PLANNER)
    )


def make_quote(request_id: str, gpo_contract_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_quote(
            request_id, create_quote_payload(gpo_contract_id, **overrides), PLANNER
        )
    )


def accept_quote(quote_id: str, **payload) -> dict:
    return get_success_data(api_client.accept_quote(quote_id, PLANNER, payload or None))


def make_project(request_id: str, facility_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_installation_project(
            request_id, create_project_payload(**overrides),
            make_facility_director_headers(facility_id),
        )
    )


def advance_equipment(project_id: str, facility_id: str, steps: int = 1) -> dict:
    data = None
    for _ in range(steps):
        data = get_success_data(
            api_client.advance_equipment(project_id, make_facility_director_headers(facility_id))
        )
    return data


def advance_construction(project_id: str, facility_id: str, steps: int = 1) -> dict:
    data = None
    for _ in range(steps):
        data = get_success_data(
            api_client.advance_construction(project_id, make_facility_director_headers(facility_id))
        )
    return data


def take_live(project_id: str, facility_id: str) -> dict:
    return get_success_data(
        api_client.go_live_project(project_id, make_facility_director_headers(facility_id))
    )


def cancel_project(project_id: str, **payload) -> dict:
    return get_success_data(api_client.cancel_project(project_id, PLANNER, payload or None))


def schedule_audit(request_id: str, project_id: str, window_start: str, window_end: str) -> dict:
    return get_success_data(
        api_client.create_audit(
            request_id, create_audit_payload(project_id, window_start, window_end), AUDITOR
        )
    )


def collect_audit(audit_id: str, actual_annual_volume: int, actual_annual_opex_cents: int) -> dict:
    return get_success_data(
        api_client.collect_audit(
            audit_id, collect_audit_payload(actual_annual_volume, actual_annual_opex_cents), AUDITOR
        )
    )


def decommission(asset_id: str, disposition: str) -> dict:
    return get_success_data(
        api_client.decommission_asset(asset_id, decommission_payload(disposition), PLANNER)
    )


# ─── Read-back helpers ────────────────────────────────────────────────


def refresh_facility(facility_id: str) -> dict:
    return get_success_data(api_client.get_facility(facility_id, PLANNER))


def refresh_department(department_id: str) -> dict:
    return get_success_data(api_client.get_department(department_id, PLANNER))


def refresh_asset(asset_id: str) -> dict:
    return get_success_data(api_client.get_asset(asset_id, PLANNER))


def refresh_cycle(cycle_id: str) -> dict:
    return get_success_data(api_client.get_cycle(cycle_id, PLANNER))


def refresh_request(request_id: str) -> dict:
    return get_success_data(api_client.get_request(request_id, PLANNER))


def refresh_allocation(allocation_id: str) -> dict:
    return get_success_data(api_client.get_allocation(allocation_id, PLANNER))


def refresh_quote(quote_id: str) -> dict:
    return get_success_data(api_client.get_quote(quote_id, PLANNER))


def refresh_project(project_id: str) -> dict:
    return get_success_data(api_client.get_installation_project(project_id, PLANNER))


def refresh_audit(audit_id: str) -> dict:
    return get_success_data(api_client.get_audit(audit_id, PLANNER))


def refresh_member(member_id: str) -> dict:
    return get_success_data(api_client.get_committee_member(member_id, PLANNER))


def allocation_rows(cycle_id: str, facility_id: str = None, **filters) -> list:
    params = {"cycle_id": cycle_id, "limit": 100}
    if facility_id:
        params["facility_id"] = facility_id
    params.update(filters)
    return get_success_data(api_client.list_allocations(PLANNER, params=params))


def live_allocation(cycle_id: str, facility_id: str) -> dict:
    """The one allocation row of this cycle and facility whose posture is not SUPERSEDED."""
    rows = [r for r in allocation_rows(cycle_id, facility_id) if r["posture"] != "SUPERSEDED"]
    assert len(rows) == 1, f"expected exactly one live allocation row, found {len(rows)}"
    return rows[0]


def score_rows(request_id: str, **filters) -> list:
    params = {"limit": 100}
    params.update(filters)
    return get_success_data(api_client.list_request_scores(request_id, PLANNER, params=params))


def vote_rows(request_id: str, **filters) -> list:
    params = {"limit": 100}
    params.update(filters)
    return get_success_data(api_client.list_request_votes(request_id, PLANNER, params=params))


def service_event_rows(asset_id: str, **filters) -> list:
    params = {"limit": 100}
    params.update(filters)
    return get_success_data(api_client.list_service_events(asset_id, PLANNER, params=params))


def latest_score(request_id: str) -> dict:
    rows = score_rows(request_id)
    assert rows, f"request {request_id} has no score history"
    return max(rows, key=lambda row: row["sequence"])


# ─── Tier 1: the estate ───────────────────────────────────────────────


def setup_estate(facility: dict = None, department: dict = None, asset: dict = None,
                 clock: str = CLOCK_START) -> dict:
    """Facility NRH + a CT department + the CT scanner AC, clock pinned.

    Returns a context dict carrying `facility`, `department` and `asset`.
    """
    pin_clock(clock)
    fac = make_facility(**(facility or {}))
    dept = make_department(fac["id"], **(department or {}))
    ast = make_asset(fac["id"], dept["id"], **(asset or {}))
    return {"facility": fac, "department": dept, "asset": ast}


def setup_intake_open_cycle(cycle: dict = None, **estate_overrides) -> dict:
    """Estate plus a capital cycle advanced from DRAFT to INTAKE_OPEN."""
    ctx = setup_estate(**estate_overrides)
    ctx["cycle"] = make_cycle(**(cycle or {}))
    ctx["cycle"] = open_intake(ctx["cycle"]["id"])
    return ctx


def setup_draft_request(request: dict = None, **overrides) -> dict:
    """Estate + INTAKE_OPEN cycle + one DRAFT replacement request."""
    ctx = setup_intake_open_cycle(**overrides)
    ctx["request"] = make_request(
        ctx["cycle"]["id"], ctx["department"]["id"], ctx["asset"]["id"], **(request or {})
    )
    return ctx


def setup_screened_request(**overrides) -> dict:
    """Draft request driven through submit and an ACCEPT screening."""
    ctx = setup_draft_request(**overrides)
    ctx["request"] = submit(ctx["request"]["id"], ctx["department"]["id"])
    ctx["request"] = screen(ctx["request"]["id"], "ACCEPT")
    return ctx


def setup_scored_request(**overrides) -> dict:
    """The canonical scored fixture: one SCORED request in a SCORING cycle."""
    ctx = setup_screened_request(**overrides)
    close_intake(ctx["cycle"]["id"])
    ctx["cycle"] = run_scoring(ctx["cycle"]["id"])
    ctx["request"] = refresh_request(ctx["request"]["id"])
    return ctx


def setup_allocated_cycle(allocation_method: str = "PRO_RATA", **overrides) -> dict:
    """Scored fixture plus an allocation run, leaving the cycle ALLOCATED."""
    ctx = setup_scored_request(**overrides)
    ctx["cycle"] = run_allocation(
        ctx["cycle"]["id"], allocation_method, ctx["cycle"]["version"]
    )
    ctx["allocation"] = live_allocation(ctx["cycle"]["id"], ctx["facility"]["id"])
    return ctx


def setup_approved_request(chair_weight: int = 3, **overrides) -> dict:
    """Allocated cycle plus a system-wide chair whose APPROVE ballot carries the request.

    A single chair of weight 3 is the whole electorate, so cast weight meets the
    sixty-percent quorum bar and approve weight clears the two-thirds bar.
    """
    ctx = setup_allocated_cycle(**overrides)
    ctx["chair"] = make_member("CHAIR", chair_weight)
    cast_vote(ctx["request"]["id"], ctx["chair"]["id"], "APPROVE")
    ctx["request"] = close_voting(ctx["request"]["id"], ctx["chair"]["id"])
    ctx["cycle"] = refresh_cycle(ctx["cycle"]["id"])
    return ctx


def setup_funded_request(**overrides) -> dict:
    """Approved request funded by the second planner identity."""
    ctx = setup_approved_request(**overrides)
    ctx["request"] = fund(ctx["request"]["id"])
    ctx["allocation"] = refresh_allocation(ctx["allocation"]["id"])
    ctx["cycle"] = refresh_cycle(ctx["cycle"]["id"])
    ctx["asset"] = refresh_asset(ctx["asset"]["id"])
    return ctx


def setup_project(project: dict = None, **overrides) -> dict:
    """Funded request plus an installation project opened by the facility director."""
    ctx = setup_funded_request(**overrides)
    ctx["project"] = make_project(
        ctx["request"]["id"], ctx["facility"]["id"], **(project or {})
    )
    return ctx


def setup_commissioned_project(**overrides) -> dict:
    """Installation project whose equipment axis has reached COMMISSIONED."""
    ctx = setup_project(**overrides)
    ctx["project"] = advance_equipment(ctx["project"]["id"], ctx["facility"]["id"], steps=3)
    return ctx


def setup_implemented_request(**overrides) -> dict:
    """Commissioned project taken live, moving the request to IMPLEMENTED."""
    ctx = setup_commissioned_project(**overrides)
    ctx["project"] = take_live(ctx["project"]["id"], ctx["facility"]["id"])
    ctx["request"] = refresh_request(ctx["request"]["id"])
    return ctx


def setup_scheduled_audit(window_start: str = CLOCK_START,
                          window_end: str = "2027-08-01T00:00:00Z", **overrides) -> dict:
    """Implemented request plus a SCHEDULED utilization audit."""
    ctx = setup_implemented_request(**overrides)
    ctx["audit"] = schedule_audit(
        ctx["request"]["id"], ctx["project"]["id"], window_start, window_end
    )
    return ctx


# ─── Tier 2: group purchasing and quotes ──────────────────────────────


def setup_quoted_request(contract: dict = None, quote: dict = None,
                         base: str = "approved", **overrides) -> dict:
    """A live group-purchasing contract plus one SUBMITTED quote on the request.

    `base` selects the state the owning request is driven to first: "scored",
    "allocated", "approved" (the default) or "funded".
    """
    builders = {
        "scored": setup_scored_request,
        "allocated": setup_allocated_cycle,
        "approved": setup_approved_request,
        "funded": setup_funded_request,
    }
    ctx = builders[base](**overrides)
    ctx["contract"] = make_gpo_contract(**(contract or {}))
    ctx["quote"] = make_quote(ctx["request"]["id"], ctx["contract"]["id"], **(quote or {}))
    return ctx


# ─── Tier 3: multi-facility scenarios ─────────────────────────────────


def setup_two_facility_cycle(cycle: dict = None, facility_a: dict = None, facility_b: dict = None,
                             department_a: dict = None, department_b: dict = None,
                             asset_a: dict = None, asset_b: dict = None,
                             request_a: dict = None, request_b: dict = None,
                             clock: str = CLOCK_START) -> dict:
    """Two facilities, each with one department, asset and SCORED request.

    Returns a context whose keys are suffixed `_a` and `_b`, plus the shared
    `cycle` left in SCORING after the scoring run.
    """
    pin_clock(clock)
    fac_a = make_facility(**(facility_a or {}))
    fac_b = make_facility(
        **{"name": "South Regional Hospital", "code": "SRH", "region": "SOUTH",
           **(facility_b or {})}
    )
    dept_a = make_department(fac_a["id"], **(department_a or {}))
    dept_b = make_department(fac_b["id"], **(department_b or {}))
    ast_a = make_asset(fac_a["id"], dept_a["id"], **(asset_a or {}))
    ast_b = make_asset(fac_b["id"], dept_b["id"], **(asset_b or {}))
    cyc = make_cycle(**(cycle or {}))
    cyc = open_intake(cyc["id"])
    req_a = make_request(cyc["id"], dept_a["id"], ast_a["id"], **(request_a or {}))
    req_b = make_request(cyc["id"], dept_b["id"], ast_b["id"], **(request_b or {}))
    for req, dept in ((req_a, dept_a), (req_b, dept_b)):
        submit(req["id"], dept["id"])
        screen(req["id"], "ACCEPT")
    close_intake(cyc["id"])
    cyc = run_scoring(cyc["id"])
    return {
        "facility_a": fac_a,
        "facility_b": fac_b,
        "department_a": dept_a,
        "department_b": dept_b,
        "asset_a": ast_a,
        "asset_b": ast_b,
        "cycle": cyc,
        "request_a": refresh_request(req_a["id"]),
        "request_b": refresh_request(req_b["id"]),
    }


def setup_second_request(ctx: dict, asset: dict = None, request: dict = None,
                         department: dict = None) -> dict:
    """Add a second department, asset and SCORED request to an existing cycle.

    Only usable while the cycle still admits submissions, so callers pass a
    context built by `setup_intake_open_cycle`.
    """
    dept = make_department(ctx["facility"]["id"], **(department or {"name": "Diagnostic Imaging CT-2"}))
    ast = make_asset(ctx["facility"]["id"], dept["id"], **(asset or {"model_name": "Aquilon CT-9"}))
    req = make_request(ctx["cycle"]["id"], dept["id"], ast["id"], **(request or {}))
    submit(req["id"], dept["id"])
    screen(req["id"], "ACCEPT")
    return {"department": dept, "asset": ast, "request": req}
