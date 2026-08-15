"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only. Setup calls use get_success_data() so a broken
precondition fails loudly as "Setup failed" rather than as a confusing
assertion error.

Identity threading: SalesRep calls are entity-backed by SalesRep, so
submission/dispute helpers build per-instance headers from the real rep id via
make_sales_rep_headers; change-request helpers thread the opaque creator /
approver user ids through make_analyst_headers / make_manager_headers.

Creation-order determinism: several PRD rules distribute remainder cents or
break ties "in creation order". The creators for territories, rep assignments,
and assignment rules nudge the logical clock forward by one second before each
creation so that created_at timestamps are strictly increasing in call order
and every creation-order tie-break is deterministic. The clock is only ever
driven forward, and explicit clock sets in scenario builders always jump to
later plan-year dates, so the nudges never disturb date-sensitive preconditions.
"""
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import STANDARD_RAMP_MULTIPLIERS
from .factories import (
    create_account_payload,
    create_allocation_payload,
    create_change_request_payload,
    create_credit_event_payload,
    create_dispute_payload,
    create_geo_rule_payload,
    create_named_rule_payload,
    create_plan_year_payload,
    create_ramp_schedule_payload,
    create_rep_assignment_payload,
    create_rep_payload,
    create_submission_payload,
    create_territory_payload,
)
from .test_users import (
    TEST_USERS,
    make_analyst_headers,
    make_manager_headers,
    make_sales_rep_headers,
)

ADMIN = TEST_USERS["admin_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation and reads
# ---------------------------------------------------------------------------

def create_plan(**overrides):
    """Create a plan year. Returns the plan dict (status DRAFT, version 1)."""
    return get_success_data(
        api_client.create_plan_year(create_plan_year_payload(**overrides), ADMIN))


def get_plan(plan_id):
    return get_success_data(api_client.get_plan_year(plan_id, ADMIN))


def plan_version(plan_id):
    return get_plan(plan_id)["version"]


def add_territory(plan_id, name=None, potential_cents=100,
                  headcount_capacity=2, parent_territory_id=None):
    tick_clock()
    payload = create_territory_payload(
        plan_id, potential_cents=potential_cents,
        headcount_capacity=headcount_capacity)
    if name is not None:
        payload["name"] = name
    if parent_territory_id is not None:
        payload["parent_territory_id"] = parent_territory_id
    return get_success_data(api_client.create_territory(payload, ADMIN))


def get_territory(territory_id):
    return get_success_data(api_client.get_territory(territory_id, ADMIN))


def activate_territory(territory_id):
    return get_success_data(api_client.activate_territory(territory_id, ADMIN))


def create_rep(hire_date="2025-01-05", full_name=None, email=None):
    payload = create_rep_payload(hire_date=hire_date)
    if full_name is not None:
        payload["full_name"] = full_name
    if email is not None:
        payload["email"] = email
    return get_success_data(api_client.create_rep(payload, ADMIN))


def create_ramp_schedule(multipliers=None, name=None):
    payload = create_ramp_schedule_payload()
    if multipliers is not None:
        payload["multipliers"] = multipliers
    if name is not None:
        payload["name"] = name
    return get_success_data(api_client.create_ramp_schedule(payload, ADMIN))


def create_assignment(plan_id, rep_id, territory_id,
                      effective_from="2027-01-01", effective_to=None,
                      ramp_schedule_id=None):
    tick_clock()
    payload = create_rep_assignment_payload(
        plan_id, rep_id, territory_id, effective_from=effective_from)
    if effective_to is not None:
        payload["effective_to"] = effective_to
    if ramp_schedule_id is not None:
        payload["ramp_schedule_id"] = ramp_schedule_id
    return get_success_data(api_client.create_rep_assignment(payload, ADMIN))


def get_assignment(assignment_id):
    return get_success_data(api_client.get_rep_assignment(assignment_id, ADMIN))


def create_geo_rule(plan_id, territory_id, priority=10, country_code="US",
                    state_code=None, segment=None):
    tick_clock()
    payload = create_geo_rule_payload(plan_id, territory_id, priority=priority,
                                      country_code=country_code)
    if state_code is not None:
        payload["state_code"] = state_code
    if segment is not None:
        payload["segment"] = segment
    return get_success_data(api_client.create_assignment_rule(payload, ADMIN))


def create_named_rule(plan_id, territory_id, account_id, priority=5):
    tick_clock()
    payload = create_named_rule_payload(plan_id, territory_id, account_id,
                                        priority=priority)
    return get_success_data(api_client.create_assignment_rule(payload, ADMIN))


def create_account(plan_id, name=None, country_code="US", segment="SMB",
                   annual_potential_cents=50000, state_code=None):
    payload = create_account_payload(
        plan_id, country_code=country_code, segment=segment,
        annual_potential_cents=annual_potential_cents)
    if name is not None:
        payload["name"] = name
    if state_code is not None:
        payload["state_code"] = state_code
    return get_success_data(api_client.create_account(payload, ADMIN))


def get_account(account_id):
    return get_success_data(api_client.get_account(account_id, ADMIN))


# ---------------------------------------------------------------------------
# Tier 2: plan lifecycle and OCC-guarded writes
# ---------------------------------------------------------------------------

def open_plan(plan_id):
    return get_success_data(api_client.open_plan(plan_id, ADMIN))


def close_submissions(plan_id):
    return get_success_data(api_client.close_submissions(plan_id, ADMIN))


def communicate_plan(plan_id):
    return get_success_data(api_client.communicate_plan(plan_id, ADMIN))


def lock_plan(plan_id):
    return get_success_data(api_client.lock_plan(plan_id, ADMIN))


def set_clock(to_iso8601):
    result = get_success_data(api_client.set_clock(to_iso8601, ADMIN))
    dt = datetime.strptime(to_iso8601, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc)
    if dt > _clock_state["last"]:
        _clock_state["last"] = dt
    return result


# Session-wide furthest instant the logical clock has been driven to. The
# server clock resets to 2026-08-01T00:00:00Z on every per-test restart, which
# is always behind this tracker, so ticking forward from the tracker is always
# a forward move for the server as well.
_clock_state = {"last": datetime(2026, 8, 1, tzinfo=timezone.utc)}


def tick_clock():
    """Advance the logical clock one second past the furthest instant driven
    so far this session, keeping creation-order tie-breaks deterministic."""
    _clock_state["last"] = _clock_state["last"] + timedelta(seconds=1)
    iso = _clock_state["last"].strftime("%Y-%m-%dT%H:%M:%SZ")
    return get_success_data(api_client.set_clock(iso, ADMIN))


def evaluate_assignments(plan_id):
    return get_success_data(api_client.evaluate_assignments(plan_id, ADMIN))


def create_allocation(plan_id, scope_territory_id, pool_cents):
    return get_success_data(api_client.create_allocation(
        create_allocation_payload(plan_id, scope_territory_id, pool_cents),
        ADMIN))


def apply_allocation(allocation_id, plan_id):
    """Apply a DRAFT allocation, reading the plan version fresh (OCC)."""
    return get_success_data(api_client.apply_allocation(
        allocation_id, plan_version(plan_id), ADMIN))


def create_and_apply_allocation(plan_id, scope_territory_id, pool_cents):
    alloc = create_allocation(plan_id, scope_territory_id, pool_cents)
    return apply_allocation(alloc["id"], plan_id)


def compute_run(plan_id):
    from .factories import create_reconciliation_run_payload
    return get_success_data(api_client.create_reconciliation_run(
        create_reconciliation_run_payload(plan_id), ADMIN))


def apply_run(run_id, plan_id):
    """Apply a COMPUTED reconciliation run, reading the plan version fresh."""
    return get_success_data(api_client.apply_reconciliation_run(
        run_id, plan_version(plan_id), ADMIN))


def compute_and_apply_run(plan_id):
    run = compute_run(plan_id)
    return apply_run(run["id"], plan_id)


def walk_to_submissions_closed(plan_id):
    return close_submissions(plan_id)


def walk_to_reconciled(plan_id):
    """close-submissions -> compute -> apply. Returns the APPLIED run."""
    close_submissions(plan_id)
    return compute_and_apply_run(plan_id)


def walk_to_communicated(plan_id):
    """close-submissions -> compute -> apply -> communicate. Returns the run."""
    run = walk_to_reconciled(plan_id)
    communicate_plan(plan_id)
    return run


# ---------------------------------------------------------------------------
# Tier 3: role-threaded operations (submissions, change requests, disputes)
# ---------------------------------------------------------------------------

def submit(plan_id, territory_id, proposed_quota_cents, rep_id,
           rationale=None):
    """Create a bottom-up submission as the SalesRep with id `rep_id`."""
    payload = create_submission_payload(plan_id, territory_id,
                                        proposed_quota_cents)
    if rationale is not None:
        payload["rationale"] = rationale
    return get_success_data(api_client.create_submission(
        payload, make_sales_rep_headers(rep_id)))


def get_submission(submission_id):
    return get_success_data(api_client.get_submission(submission_id, ADMIN))


def create_change_request(plan_id, account_id, from_territory_id,
                          to_territory_id, effective_date,
                          creator="analyst-1", reason=None):
    payload = create_change_request_payload(
        plan_id, account_id, from_territory_id, to_territory_id,
        effective_date)
    if reason is not None:
        payload["reason"] = reason
    return get_success_data(api_client.create_change_request(
        payload, make_analyst_headers(creator)))


def get_change_request(request_id):
    return get_success_data(api_client.get_change_request(request_id, ADMIN))


def approve_change_request(request_id, plan_id, approver="mgr-1"):
    """Approve a PENDING change request, reading the plan version fresh."""
    return get_success_data(api_client.approve_change_request(
        request_id, plan_version(plan_id), make_manager_headers(approver)))


def apply_change_request(request_id, approver="mgr-1"):
    return get_success_data(api_client.apply_change_request(
        request_id, make_manager_headers(approver)))


def file_dispute(plan_id, account_id, claimant_territory_id, rep_id,
                 reason="account belongs to my territory"):
    """File an ownership dispute as the SalesRep with id `rep_id`."""
    payload = create_dispute_payload(plan_id, account_id,
                                     claimant_territory_id, reason=reason)
    return get_success_data(api_client.create_dispute(
        payload, make_sales_rep_headers(rep_id)))


def get_dispute(dispute_id):
    return get_success_data(api_client.get_dispute(dispute_id, ADMIN))


def post_booking(plan_id, account_id, amount_cents, booking_date):
    """Post a booking; returns the list of created BOOKING events."""
    return get_success_data(api_client.create_credit_event(
        create_credit_event_payload(plan_id, account_id, amount_cents,
                                    booking_date), ADMIN))


def post_booking_at(plan_id, account_id, amount_cents, booking_date):
    """Set the logical clock to the booking date first, then post."""
    set_clock(f"{booking_date}T00:00:00Z")
    return post_booking(plan_id, account_id, amount_cents, booking_date)


# ---------------------------------------------------------------------------
# Tier 4: composite scenario builders
# ---------------------------------------------------------------------------

def setup_open_plan(year=2027, target=100000, productivity=1000000,
                    label=None, **plan_over):
    """Plan + one ACTIVE territory T + plan OPEN. Returns dict(plan, t)."""
    kwargs = dict(start_date=f"{year}-01-01", end_date=f"{year}-12-31",
                  company_target_cents=target,
                  productivity_per_rep_cents=productivity,
                  lock_date=f"{year}-01-15")
    if label is not None:
        kwargs["label"] = label
    kwargs.update(plan_over)
    plan = create_plan(**kwargs)
    t = add_territory(plan["id"], name="T")
    activate_territory(t["id"])
    plan = open_plan(plan["id"])
    return {"plan": plan, "t": t}


def setup_open_plan_with_children(potentials, target, year=2027,
                                  productivity=1000000, capacity=5,
                                  label=None, **plan_over):
    """Root R (potential 0) plus one ACTIVE child per entry of `potentials`,
    created in list order; plan OPEN. Children are named A, B, C, ... in
    creation order. Returns dict(plan, root, children)."""
    kwargs = dict(start_date=f"{year}-01-01", end_date=f"{year}-12-31",
                  company_target_cents=target,
                  productivity_per_rep_cents=productivity,
                  lock_date=f"{year}-01-15")
    if label is not None:
        kwargs["label"] = label
    kwargs.update(plan_over)
    plan = create_plan(**kwargs)
    root = add_territory(plan["id"], name="R", potential_cents=0,
                         headcount_capacity=capacity)
    children = []
    for i, pot in enumerate(potentials):
        child = add_territory(plan["id"], name=chr(ord("A") + i),
                              potential_cents=pot, headcount_capacity=capacity,
                              parent_territory_id=root["id"])
        children.append(child)
    activate_territory(root["id"])
    for child in children:
        activate_territory(child["id"])
    plan = open_plan(plan["id"])
    return {"plan": plan, "root": root, "children": children}


def setup_allocated_leaf(year=2027, target=100000, productivity=1000000,
                         label=None, **plan_over):
    """OPEN plan, single ACTIVE leaf T, allocation(pool == target) APPLIED on T.
    Returns dict(plan, t, alloc)."""
    base = setup_open_plan(year=year, target=target,
                           productivity=productivity, label=label,
                           **plan_over)
    alloc = create_and_apply_allocation(base["plan"]["id"], base["t"]["id"],
                                        target)
    base["alloc"] = alloc
    base["t"] = get_territory(base["t"]["id"])
    return base


def setup_reconciled_leaf(year=2027, target=100000, productivity=1000000,
                          with_rep=False, rep_hire="2025-01-05",
                          ramp_schedule_id=None, with_account=False,
                          account_potential=50000, label=None, **plan_over):
    """Allocated leaf + close + compute + apply. Optionally: a rep ACTIVELY
    assigned to T, a US GEO rule to T, and a US account routed to T.
    Returns dict(plan, t, alloc, run[, rep, asg, rule, acc])."""
    base = setup_allocated_leaf(year=year, target=target,
                                productivity=productivity, label=label,
                                **plan_over)
    plan_id = base["plan"]["id"]
    if with_rep:
        rep = create_rep(hire_date=rep_hire)
        asg = create_assignment(plan_id, rep["id"], base["t"]["id"],
                                ramp_schedule_id=ramp_schedule_id)
        base["rep"] = rep
        base["asg"] = asg
    if with_account:
        rule = create_geo_rule(plan_id, base["t"]["id"])
        acc = create_account(plan_id, name="ACC",
                             annual_potential_cents=account_potential)
        base["rule"] = rule
        base["acc"] = acc
    base["run"] = walk_to_reconciled(plan_id)
    base["plan"] = get_plan(plan_id)
    return base


def setup_communicated_leaf(clock=None, **kwargs):
    """Reconciled leaf + communicate; optionally sets the logical clock last.
    Returns the same dict as setup_reconciled_leaf."""
    base = setup_reconciled_leaf(**kwargs)
    communicate_plan(base["plan"]["id"])
    base["plan"] = get_plan(base["plan"]["id"])
    if clock is not None:
        set_clock(clock)
    return base


def setup_two_territory_communicated(year=2027, target=100000,
                                     account_potential=50000,
                                     rep_hire="2025-01-05",
                                     owner_name="TX", claimant_name="TY",
                                     label=None, **plan_over):
    """Plan with two ACTIVE flat territories: the owner (US accounts route to
    it via a GEO rule) and the claimant (staffed by one ACTIVE veteran rep).
    One US account; plan COMMUNICATED. Returns dict(plan, tx, ty, rep, asg,
    rule, acc, run)."""
    kwargs = dict(start_date=f"{year}-01-01", end_date=f"{year}-12-31",
                  company_target_cents=target,
                  productivity_per_rep_cents=1000000,
                  lock_date=f"{year}-01-15")
    if label is not None:
        kwargs["label"] = label
    kwargs.update(plan_over)
    plan = create_plan(**kwargs)
    plan_id = plan["id"]
    tx = add_territory(plan_id, name=owner_name)
    ty = add_territory(plan_id, name=claimant_name)
    activate_territory(tx["id"])
    activate_territory(ty["id"])
    plan = open_plan(plan_id)
    rep = create_rep(hire_date=rep_hire)
    asg = create_assignment(plan_id, rep["id"], ty["id"])
    rule = create_geo_rule(plan_id, tx["id"])
    acc = create_account(plan_id, name="A",
                         annual_potential_cents=account_potential)
    run = walk_to_communicated(plan_id)
    return {"plan": get_plan(plan_id), "tx": tx, "ty": ty, "rep": rep,
            "asg": asg, "rule": rule, "acc": acc, "run": run}


def setup_change_apply_scenario(year=2027, target=500000, tf_potential=600,
                                tt_potential=400, account_potential=240000,
                                effective_date="2027-07-10", bookings=(),
                                clock_final=None, staff_from=True,
                                staff_to=True, approve=True, apply=False,
                                creator="analyst-1", approver="mgr-1",
                                label="FY27-CAS", **plan_over):
    """Full mid-year-change scenario, ready for a change-request apply.

    Root R with ACTIVE children TF (potential tf_potential) and TT
    (potential tt_potential); plan OPEN; allocation(pool == target) applied on
    R; veteran repOld ACTIVELY assigned to TF (when staff_from) and repNew to
    TT (when staff_to); GEO rule US -> TF; account ACC (US, ENTERPRISE,
    account_potential); close; compute+apply; communicate; each
    (booking_date, amount) in `bookings` posted with the clock moved to the
    booking date; change request TF -> TT created by `creator` with the given
    effective_date; approved by `approver` when approve=True; clock moved to
    clock_final when given; the request applied when apply=True.

    Returns dict(plan, r, tf, tt, rep_old, asg_old, rep_new, asg_new, rule,
    acc, run, events, cr).
    """
    plan = create_plan(label=label, start_date=f"{year}-01-01",
                       end_date=f"{year}-12-31", company_target_cents=target,
                       productivity_per_rep_cents=1000000,
                       lock_date=f"{year}-01-15", **plan_over)
    plan_id = plan["id"]
    r = add_territory(plan_id, name="R", potential_cents=0,
                      headcount_capacity=5)
    tf = add_territory(plan_id, name="TF", potential_cents=tf_potential,
                       headcount_capacity=3, parent_territory_id=r["id"])
    tt = add_territory(plan_id, name="TT", potential_cents=tt_potential,
                       headcount_capacity=3, parent_territory_id=r["id"])
    for t in (r, tf, tt):
        activate_territory(t["id"])
    open_plan(plan_id)
    alloc = create_and_apply_allocation(plan_id, r["id"], target)

    rep_old = asg_old = rep_new = asg_new = None
    effective_from = f"{year}-01-01"
    if staff_from:
        rep_old = create_rep(hire_date="2025-01-05", full_name="Old")
        asg_old = create_assignment(plan_id, rep_old["id"], tf["id"],
                                    effective_from=effective_from)
    if staff_to:
        rep_new = create_rep(hire_date="2025-02-05", full_name="New")
        asg_new = create_assignment(plan_id, rep_new["id"], tt["id"],
                                    effective_from=effective_from)

    rule = create_geo_rule(plan_id, tf["id"])
    acc = create_account(plan_id, name="ACC", country_code="US",
                         segment="ENTERPRISE",
                         annual_potential_cents=account_potential)
    run = walk_to_communicated(plan_id)

    events = []
    for booking_date, amount in bookings:
        events.extend(post_booking_at(plan_id, acc["id"], amount,
                                      booking_date))

    cr = create_change_request(plan_id, acc["id"], tf["id"], tt["id"],
                               effective_date, creator=creator,
                               reason="realign")
    if approve:
        cr = approve_change_request(cr["id"], plan_id, approver=approver)
    if clock_final is not None:
        set_clock(clock_final)
    if apply:
        cr = apply_change_request(cr["id"], approver=approver)

    return {"plan": get_plan(plan_id), "r": r, "tf": tf, "tt": tt,
            "rep_old": rep_old, "asg_old": asg_old, "rep_new": rep_new,
            "asg_new": asg_new, "rule": rule, "acc": acc, "run": run,
            "alloc": alloc, "events": events, "cr": cr}


def setup_dual_reconciliation_policy_plans():
    """Two plans reconciled with identical inputs under the two policies.

    Plan B (BLENDED, 2027) and plan T (TOP_DOWN_WINS, 2028), each: root (pot
    0) + child (pot 1000) ACTIVE; OPEN; allocation(1000000) applied on the
    root; a veteran rep ACTIVELY assigned to the child; that rep's LOCKED_IN
    submission of 1080000 on the child; close; compute; apply.

    Returns {"b": ns, "t": ns} where each ns is dict(plan, root, child, rep,
    asg, sub, run).
    """
    out = {}
    for key, year, policy in (("b", 2027, "BLENDED"),
                              ("t", 2028, "TOP_DOWN_WINS")):
        plan = create_plan(label=f"FY-{key.upper()}",
                           start_date=f"{year}-01-01",
                           end_date=f"{year}-12-31",
                           company_target_cents=1000000,
                           productivity_per_rep_cents=2000000,
                           lock_date=f"{year}-01-15",
                           reconciliation_policy=policy)
        plan_id = plan["id"]
        root = add_territory(plan_id, name=f"R{key.upper()}",
                             potential_cents=0, headcount_capacity=5)
        child = add_territory(plan_id, name=f"T{key.upper()}",
                              potential_cents=1000, headcount_capacity=5,
                              parent_territory_id=root["id"])
        activate_territory(root["id"])
        activate_territory(child["id"])
        open_plan(plan_id)
        create_and_apply_allocation(plan_id, root["id"], 1000000)
        rep = create_rep(hire_date="2025-01-05")
        asg = create_assignment(plan_id, rep["id"], child["id"],
                                effective_from=f"{year}-01-01")
        sub = submit(plan_id, child["id"], 1080000, rep["id"])
        run = walk_to_reconciled(plan_id)
        out[key] = {"plan": get_plan(plan_id), "root": root, "child": child,
                    "rep": rep, "asg": asg, "sub": sub, "run": run}
    return out


def setup_tolerance_boundary_plan():
    """BLENDED plan whose two children sit exactly on and one cent past the
    reconciliation tolerance boundary.

    Root R (pot 0, target 2000000) + children T1, T2 (pot 1 each -> 1000000
    top-down each); rep R1 on T1 submits 1100000, rep R2 on T2 submits
    1100001; close; compute; apply. Returns dict(plan, root, t1, t2, r1, r2,
    a1, a2, s1, s2, run).
    """
    base = setup_open_plan_with_children(
        potentials=(1, 1), target=2000000, productivity=1000000,
        reconciliation_policy="BLENDED", label="FY27-TOL")
    plan_id = base["plan"]["id"]
    t1, t2 = base["children"]
    create_and_apply_allocation(plan_id, base["root"]["id"], 2000000)
    r1 = create_rep(hire_date="2025-01-05", full_name="R1")
    r2 = create_rep(hire_date="2025-01-05", full_name="R2")
    a1 = create_assignment(plan_id, r1["id"], t1["id"])
    a2 = create_assignment(plan_id, r2["id"], t2["id"])
    s1 = submit(plan_id, t1["id"], 1100000, r1["id"])
    s2 = submit(plan_id, t2["id"], 1100001, r2["id"])
    run = walk_to_reconciled(plan_id)
    return {"plan": get_plan(plan_id), "root": base["root"], "t1": t1,
            "t2": t2, "r1": r1, "r2": r2, "a1": a1, "a2": a2, "s1": s1,
            "s2": s2, "run": run}


def setup_ramp_boundary_plan():
    """Plan with leaf children T15 and T16 (120000 each after allocation) and
    two new-hire reps: R15 hired on the 15th of March, R16 on the 16th.
    Returns dict(plan, root, t15, t16, ramp, r15, r16)."""
    base = setup_open_plan_with_children(
        potentials=(1, 1), target=240000, productivity=1000000,
        label="FY27-RAMPB")
    plan_id = base["plan"]["id"]
    t15, t16 = base["children"]
    t15 = get_territory(t15["id"])
    t16 = get_territory(t16["id"])
    create_and_apply_allocation(plan_id, base["root"]["id"], 240000)
    ramp = create_ramp_schedule(STANDARD_RAMP_MULTIPLIERS, name="Std")
    r15 = create_rep(hire_date="2027-03-15", full_name="R15")
    r16 = create_rep(hire_date="2027-03-16", full_name="R16")
    return {"plan": get_plan(plan_id), "root": base["root"], "t15": t15,
            "t16": t16, "ramp": ramp, "r15": r15, "r16": r16}
