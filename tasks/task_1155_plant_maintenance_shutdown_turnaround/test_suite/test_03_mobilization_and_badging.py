"""Contractor mobilization gates, worker badging caps, debadge cascades, and
entity-backed ownership enforcement on contractor-scoped writes."""
from test_helpers import (
    ApiErrorId,
    validate_error,
    validate_success,
    advance_turnaround,
    assign_worker,
    create_shift,
    invite_contractor,
    mobilize_contractor_once,
    register_worker,
    setup_execution_turnaround,
    setup_scope_frozen,
    vet_and_badge_worker,
    make_supervisor_headers,
)


def test_mobilized_step_requires_a_badged_worker(api, coordinator_headers, planner_headers):
    """PRD §3.2: "Moving from `MOBILIZING` to `MOBILIZED` requires at least one
    badged worker — a `badged_headcount` of zero draws
    `ERR_NO_BADGED_WORKERS`."

    Design: Corner/state_machines/mobilize_requires_badged_worker
    """
    ta, _items = setup_scope_frozen()
    contractor = invite_contractor(ta["id"], headcount_cap=3)
    advance_turnaround(ta["id"])  # SCOPE_FROZEN -> MOBILIZATION
    mobilize_contractor_once(contractor["id"])  # INVITED -> MOBILIZING

    resp = api.mobilize_contractor(
        contractor["id"], make_supervisor_headers(contractor["id"])
    )
    validate_error(resp, ApiErrorId.ERR_NO_BADGED_WORKERS)

    worker = register_worker(contractor["id"])
    vet_and_badge_worker(worker["id"])
    contractor = mobilize_contractor_once(contractor["id"])
    assert contractor["mobilization_status"] == "MOBILIZED"


def test_execution_advance_requires_a_mobilized_contractor(api, manager_headers):
    """PRD §3.9: "Moving from `MOBILIZATION` to `EXECUTION` requires at least
    one contractor standing in `MOBILIZED`; without one the advance is rejected
    with `ERR_NO_MOBILIZED_CONTRACTOR`."

    Design: Corner/state_machines/advance_gate_no_mobilized_contractor
    """
    ta, _items = setup_scope_frozen()
    invite_contractor(ta["id"], headcount_cap=3)  # stays INVITED
    advance_turnaround(ta["id"])  # SCOPE_FROZEN -> MOBILIZATION

    resp = api.advance_turnaround(ta["id"], manager_headers)
    validate_error(resp, ApiErrorId.ERR_NO_MOBILIZED_CONTRACTOR)

    after = validate_success(api.get_turnaround(ta["id"], manager_headers))
    assert after["status"] == "MOBILIZATION"


def test_badge_rejected_once_headcount_cap_reached(
    api, coordinator_headers, planner_headers
):
    """PRD §3.2: "Badging a `VETTED` worker requires three conditions: the
    contractor is `MOBILIZING` or `MOBILIZED`, the turnaround is in
    `MOBILIZATION` or `EXECUTION`, and the contractor has headcount room — a
    `badged_headcount` already equal to the `headcount_cap` draws
    `ERR_CONTRACTOR_HEADCOUNT_CAP`."

    Design: Corner/validations/contractor_headcount_cap_boundary
    """
    ta, _items = setup_scope_frozen()
    contractor = invite_contractor(ta["id"], headcount_cap=1)
    advance_turnaround(ta["id"])  # MOBILIZATION
    mobilize_contractor_once(contractor["id"])  # MOBILIZING

    w1 = register_worker(contractor["id"], full_name="Rae Wolder")
    vet_and_badge_worker(w1["id"])  # admitted: 0 < cap 1 -> headcount becomes 1

    w2 = register_worker(contractor["id"], full_name="Ibe Nador", trade="FITTER")
    validate_success(api.vet_worker(w2["id"], coordinator_headers))

    resp = api.badge_worker(w2["id"], coordinator_headers)
    validate_error(resp, ApiErrorId.ERR_CONTRACTOR_HEADCOUNT_CAP)

    after = validate_success(api.get_contractor(contractor["id"], planner_headers))
    assert after["badged_headcount"] == 1, "rejected badge must not move the counter"


def test_debadge_cancels_assignments_and_decrements_headcount(
    api, coordinator_headers, planner_headers
):
    """PRD §3.2: "Moving a worker to `DEBADGED`, whether from `BADGED` or
    `SUSPENDED` and whether by a coordinator's request or by the demobilization
    cascade, cancels every one of that worker's `ASSIGNED` shift assignments
    and lowers `badged_headcount` by one."

    Design: Corner/state_machines/worker_debadge_cancels_assignments
    """
    ctx = setup_execution_turnaround()
    contractor = ctx["contractor"]
    worker = ctx["workers"][0]
    shift = create_shift(ctx["turnaround"]["id"], planned_headcount=3)
    assignment = assign_worker(shift["id"], worker["id"], planned_hours=8)
    assert assignment["status"] == "ASSIGNED"

    debadged = validate_success(
        api.badge_transition_worker(worker["id"], {"to": "DEBADGED"}, coordinator_headers)
    )
    assert debadged["badge_status"] == "DEBADGED"

    assignments = validate_success(
        api.list_worker_assignments(worker["id"], planner_headers)
    )
    target = [a for a in assignments if a["id"] == assignment["id"]]
    assert target and target[0]["status"] == "CANCELLED", (
        "debadging must cancel the worker's ASSIGNED assignments"
    )

    after = validate_success(api.get_contractor(contractor["id"], planner_headers))
    assert after["badged_headcount"] == 0


def test_supervisor_of_other_contractor_cannot_register_worker(api):
    """PRD §2.1: "Concretely, mobilizing a contractor, registering a worker
    under a contractor, and submitting a contractor's daily report all require
    the acting supervisor's `X-User-ID` to equal the target contractor's `id`;
    a mismatch is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/supervisor_of_other_contractor_cannot_register_worker
    """
    ta, _items = setup_scope_frozen()
    contractor_a = invite_contractor(
        ta["id"], name="Alpha Scaffolding", craft="SCAFFOLDING", headcount_cap=3
    )
    contractor_b = invite_contractor(
        ta["id"], name="Beta Insulation", craft="INSULATION", headcount_cap=3
    )

    resp = api.register_worker(
        contractor_a["id"],
        {"full_name": "Mallory Intruder", "trade": "WELDER"},
        make_supervisor_headers(contractor_b["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
