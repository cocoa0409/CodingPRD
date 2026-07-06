"""Composite setup helpers.

Every fixture builds its preconditions from scratch (the harness restarts the
server with an empty database before each test) using only PRD-declared
endpoints, and uses get_success_data() so setup failures surface clearly.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_MID
from .factories import (
    create_budget_cycle_payload,
    create_category_payload,
    create_resident_payload,
    create_proposal_payload,
    create_cost_line_item_payload,
    create_ballot_entry_payload,
    create_milestone_payload,
)
from .test_users import (
    TEST_USERS,
    make_resident_headers,
    make_reviewer_headers,
    make_budget_admin_headers,
    make_anonymous_headers,
)

ADMIN = TEST_USERS["budget_admin_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]
ANON = TEST_USERS["anonymous_headers"]


# --------------------------------------------------------------------------
# Granular building blocks
# --------------------------------------------------------------------------

def set_clock(api, iso: str):
    return get_success_data(api.set_clock(iso, ADMIN))


def new_cycle(api, **overrides) -> dict:
    return get_success_data(api.create_budget_cycle(create_budget_cycle_payload(**overrides), ADMIN))


def new_category(api, cycle_id, **overrides) -> dict:
    return get_success_data(api.create_category(cycle_id, create_category_payload(**overrides), ADMIN))


def new_resident(api, **overrides) -> dict:
    return get_success_data(api.create_resident(create_resident_payload(**overrides), ANON))


def verify_resident(api, resident_id) -> dict:
    """UNVERIFIED -> PENDING_VERIFICATION -> VERIFIED."""
    get_success_data(api.request_verification(resident_id, {}, make_resident_headers(resident_id)))
    return get_success_data(api.decide_verification(resident_id, {"decision": "APPROVE"}, REVIEWER))


def transition(api, cycle_id, target_phase):
    return get_success_data(
        api.transition_phase(cycle_id, {"target_phase": target_phase}, ADMIN)
    )


def advance_to(api, cycle_id, target_phase):
    """Walk the linear pipeline from DRAFT up to target_phase."""
    pipeline = ["SUBMISSION", "DEVELOPMENT", "VOTING", "SELECTION", "IMPLEMENTATION", "CLOSED"]
    for phase in pipeline:
        transition(api, cycle_id, phase)
        if phase == target_phase:
            return


def cycle_version(api, cycle_id) -> int:
    return get_success_data(api.get_budget_cycle(cycle_id, ADMIN))["version"]


def get_category(api, cycle_id, category_id) -> dict:
    """Read a single category by listing the cycle's categories (there is no
    single-category GET endpoint) and selecting by id."""
    data = get_success_data(api.list_categories(cycle_id, ADMIN, params={"limit": 100}))
    for cat in data:
        if cat["id"] == category_id:
            return cat
    raise AssertionError(f"category {category_id} not found under cycle {cycle_id}")


def new_proposal(api, cycle_id, category_id, resident_id, **overrides) -> dict:
    return get_success_data(
        api.create_proposal(
            cycle_id,
            create_proposal_payload(category_id, **overrides),
            make_resident_headers(resident_id),
        )
    )


def submit_proposal(api, proposal_id, resident_id) -> dict:
    return get_success_data(api.submit_proposal(proposal_id, make_resident_headers(resident_id)))


def approve_proposal(api, proposal_id) -> dict:
    return get_success_data(
        api.review_proposal(proposal_id, {"decision": "APPROVE"}, REVIEWER)
    )


def add_line_item(api, proposal_id, **overrides) -> dict:
    return get_success_data(
        api.add_cost_line_item(proposal_id, create_cost_line_item_payload(**overrides), REVIEWER)
    )


def finalize(api, proposal_id) -> dict:
    return get_success_data(api.finalize_cost(proposal_id, REVIEWER))


def open_ballot(api, cycle_id, resident_id) -> dict:
    return get_success_data(api.create_ballot(cycle_id, make_resident_headers(resident_id)))


def add_entry(api, ballot_id, resident_id, proposal_id, **overrides) -> dict:
    return get_success_data(
        api.add_ballot_entry(
            ballot_id,
            create_ballot_entry_payload(proposal_id, **overrides),
            make_resident_headers(resident_id),
        )
    )


def cast_ballot(api, ballot_id, resident_id) -> dict:
    return get_success_data(api.cast_ballot(ballot_id, make_resident_headers(resident_id)))


def run_selection(api, cycle_id, expected_version=None) -> dict:
    if expected_version is None:
        expected_version = cycle_version(api, cycle_id)
    return get_success_data(
        api.create_selection_run(
            cycle_id, {"expected_budgetcycle_version": expected_version}, ADMIN
        )
    )


# --------------------------------------------------------------------------
# Scenario builders
# --------------------------------------------------------------------------

def scenario_developing_proposal(
    api,
    *,
    voting_method="ALLOCATION",
    clock=CLOCK_MID,
    min_voter_age=16,
    total_budget=100_000,
    per_project_cap=100_000,
    per_voter_cap=1_000_000,
    category_cap=100_000,
    verify=True,
    title="P",
    cycle_name="PB",
):
    """Cycle in DEVELOPMENT with one approved proposal in DEVELOPING (no cost
    line items yet). Returns a dict of ids: cyc, cat, rid, pid."""
    if clock is not None:
        set_clock(api, clock)
    cyc = new_cycle(
        api,
        name=cycle_name,
        voting_method=voting_method,
        min_voter_age=min_voter_age,
        total_budget_cents=total_budget,
        per_project_cap_cents=per_project_cap,
        per_voter_allocation_cap_cents=per_voter_cap,
    )
    cat = new_category(api, cyc["id"], category_budget_cap_cents=category_cap)
    res = new_resident(api)
    if verify:
        verify_resident(api, res["id"])
    transition(api, cyc["id"], "SUBMISSION")
    prop = new_proposal(api, cyc["id"], cat["id"], res["id"], title=title)
    submit_proposal(api, prop["id"], res["id"])
    transition(api, cyc["id"], "DEVELOPMENT")
    approve_proposal(api, prop["id"])
    return {"cyc": cyc["id"], "cat": cat["id"], "rid": res["id"], "pid": prop["id"]}


def scenario_costed_proposal(api, *, line_items=None, **kw):
    """Cycle in DEVELOPMENT with one proposal walked through to COSTED.

    Returns a dict of ids: cyc, cat, rid, pid.
    """
    sc = scenario_developing_proposal(api, **kw)
    if line_items is None:
        line_items = [{"unit_cost_cents": 30_000, "quantity": 1, "contingency_pct": 0.10}]
    for li in line_items:
        add_line_item(api, sc["pid"], **li)
    finalize(api, sc["pid"])
    return sc


def scenario_on_ballot_proposal(api, **kw):
    """As scenario_costed_proposal, then advance the cycle into VOTING so the
    proposal cascades COSTED -> ON_BALLOT."""
    sc = scenario_costed_proposal(api, **kw)
    transition(api, sc["cyc"], "VOTING")
    return sc


def scenario_cast_allocation_ballot(api, *, allocated_cents=5000, **kw):
    """ALLOCATION cycle in VOTING; verified resident with a CAST ballot
    allocating `allocated_cents` to the single ON_BALLOT proposal."""
    kw.setdefault("voting_method", "ALLOCATION")
    sc = scenario_on_ballot_proposal(api, **kw)
    bid = open_ballot(api, sc["cyc"], sc["rid"])["id"]
    add_entry(api, bid, sc["rid"], sc["pid"], allocated_cents=allocated_cents)
    cast_ballot(api, bid, sc["rid"])
    sc["bid"] = bid
    return sc


def scenario_selected_proposal(api, *, allocated_cents=5000, **kw):
    """Single ON_BALLOT proposal funded via a selection run; cycle in SELECTION.
    Returns ids plus `run` and `award` (the awarded amount)."""
    sc = scenario_cast_allocation_ballot(api, allocated_cents=allocated_cents, **kw)
    transition(api, sc["cyc"], "SELECTION")
    run = run_selection(api, sc["cyc"])
    sc["run"] = run["id"]
    return sc


def scenario_implementation_proposal(api, **kw):
    """Single funded proposal released into IN_IMPLEMENTATION; cycle in
    IMPLEMENTATION."""
    sc = scenario_selected_proposal(api, **kw)
    transition(api, sc["cyc"], "IMPLEMENTATION")
    get_success_data(api.release_funding(sc["pid"], ADMIN))
    return sc


def scenario_milestone(api, *, start="2026-05-01T00:00:00Z", end="2026-05-10T00:00:00Z", **kw):
    """Funded IN_IMPLEMENTATION proposal with one PLANNED milestone."""
    sc = scenario_implementation_proposal(api, **kw)
    mid = get_success_data(
        api.create_milestone(
            sc["pid"], create_milestone_payload(title="M1", scheduled_start=start, scheduled_end=end), REVIEWER
        )
    )["id"]
    sc["mid"] = mid
    return sc


def scenario_milestone_in_progress(api, **kw):
    """Funded IN_IMPLEMENTATION proposal with one milestone at IN_PROGRESS."""
    sc = scenario_milestone(api, **kw)
    get_success_data(
        api.transition_milestone(sc["mid"], {"target_status": "IN_PROGRESS"}, REVIEWER)
    )
    return sc


def scenario_voting_cycle(
    api,
    *,
    dob="1990-01-01",
    min_voter_age=16,
    voting_method="ALLOCATION",
    per_voter_cap=100_000,
    resident_state="verified",  # "unverified" | "pending" | "verified"
    clock=CLOCK_MID,
    cycle_name="PBvote",
):
    """A cycle advanced to VOTING (no proposals) plus one resident whose
    eligibility_status matches `resident_state`. Returns {cyc, cat, rid}."""
    if clock is not None:
        set_clock(api, clock)
    cyc = new_cycle(
        api,
        name=cycle_name,
        voting_method=voting_method,
        min_voter_age=min_voter_age,
        per_voter_allocation_cap_cents=per_voter_cap,
    )
    cat = new_category(api, cyc["id"])
    res = new_resident(api, date_of_birth=dob)
    if resident_state in ("pending", "verified"):
        get_success_data(
            api.request_verification(res["id"], {}, make_resident_headers(res["id"]))
        )
    if resident_state == "verified":
        get_success_data(
            api.decide_verification(res["id"], {"decision": "APPROVE"}, REVIEWER)
        )
    advance_to(api, cyc["id"], "VOTING")
    return {"cyc": cyc["id"], "cat": cat["id"], "rid": res["id"]}


def scenario_multi_proposal_on_ballot(
    api,
    *,
    voting_method,
    proposal_specs,
    n_residents=1,
    clock=CLOCK_MID,
    total_budget=1_000_000,
    per_project_cap=1_000_000,
    per_voter_cap=1_000_000,
    category_cap=1_000_000,
    cycle_name="PBmulti",
):
    """A cycle in VOTING with several ON_BALLOT proposals and one or more verified
    residents.

    proposal_specs: list of dicts, each optionally carrying `title` and `line_items`
    (default single line 1000 x1 @0.10). All proposals are filed by residents[0].

    Returns {cyc, cat, residents: [ids...], proposals: [ids...]}.
    """
    if clock is not None:
        set_clock(api, clock)
    residents = []
    for _ in range(n_residents):
        r = new_resident(api)
        verify_resident(api, r["id"])
        residents.append(r["id"])
    cyc = new_cycle(
        api,
        name=cycle_name,
        voting_method=voting_method,
        total_budget_cents=total_budget,
        per_project_cap_cents=per_project_cap,
        per_voter_allocation_cap_cents=per_voter_cap,
    )
    cat = new_category(api, cyc["id"], category_budget_cap_cents=category_cap)
    transition(api, cyc["id"], "SUBMISSION")
    proposals = []
    for i, spec in enumerate(proposal_specs):
        prop = new_proposal(api, cyc["id"], cat["id"], residents[0], title=spec.get("title", f"P{i}"))
        submit_proposal(api, prop["id"], residents[0])
        proposals.append(prop["id"])
    transition(api, cyc["id"], "DEVELOPMENT")
    for pid, spec in zip(proposals, proposal_specs):
        approve_proposal(api, pid)
        lines = spec.get("line_items", [{"unit_cost_cents": 1000, "quantity": 1, "contingency_pct": 0.10}])
        for li in lines:
            add_line_item(api, pid, **li)
        finalize(api, pid)
    transition(api, cyc["id"], "VOTING")
    return {"cyc": cyc["id"], "cat": cat["id"], "residents": residents, "proposals": proposals}


def scenario_empty_selection_ready(api, *, total_budget=100_000, category_cap=100_000):
    """Cycle with one category and NO proposals, advanced to SELECTION.
    Returns cyc id and the pre-run version."""
    cyc = new_cycle(api, name="PBempty", total_budget_cents=total_budget)
    new_category(api, cyc["id"], category_budget_cap_cents=category_cap)
    advance_to(api, cyc["id"], "SELECTION")
    return {"cyc": cyc["id"], "ver": cycle_version(api, cyc["id"])}
