"""Composite setup helpers — multi-step preambles encapsulated for tests.

Identity-threading rule (PRD §2.1): Manager and Employee identity is entity_backed:User.
For every ownership-gated call (publish, KR mutation, progress, accept-link, co-owner,
access-grant, self-submit), the caller MUST present X-User-ID == owner_user_id (or
active co-owner). These helpers ALWAYS use make_employee_headers / make_manager_headers
with the actual User.id of the resource owner — never a shared constant — to ensure the
fixture mints an identity that the PRD's ownership check will accept.
"""
import uuid

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_department_payload,
    create_user_payload,
    create_cycle_payload,
    create_objective_payload,
    create_kr_payload,
    create_numeric_kr_payload,
    create_percentage_kr_payload,
    create_milestone_kr_payload,
    create_value_change_payload,
    create_milestone_toggle_payload,
    create_alignment_link_payload,
    create_co_owner_payload,
    create_access_grant_payload,
    self_submit_payload,
    manager_submit_payload,
    calibrate_payload,
)
from .test_users import (
    TEST_USERS,
    make_employee_headers,
    make_manager_headers,
    make_admin_headers,
    make_hrbp_headers,
)


# ---------------------------------------------------------------------------
# Tier 0 — atomic primitives (admin-driven setup)
# ---------------------------------------------------------------------------

def _admin_headers():
    return TEST_USERS["platform_admin_headers"]


def _hrbp_headers():
    return TEST_USERS["hrbp_headers"]


def create_department(**overrides):
    payload = create_department_payload(**overrides)
    resp = api_client.create_department(payload, _admin_headers())
    return get_success_data(resp)


def create_user(department_id, role_type="EMPLOYEE", manager_id=None, **overrides):
    """Create a User record. Returns the User dict.

    role_type is the User.role_type column ("EMPLOYEE" or "MANAGER") — not the
    X-User-Role header. PlatformAdmin/HRBP create users; the User row's id is then
    used to mint X-User-ID for that user via make_employee/manager_headers.
    """
    payload = create_user_payload(
        department_id=department_id,
        role_type=role_type,
        **overrides,
    )
    if manager_id is not None:
        payload["manager_id"] = manager_id
    resp = api_client.create_user(payload, _admin_headers())
    return get_success_data(resp)


def create_cycle(start=None, end=None, year=None, quarter=None, **overrides):
    """Create a DRAFT cycle. By default the factory picks a fresh non-overlapping
    [start_date, end_date) window so concurrent tests on a shared server do not
    collide with ERR_CYCLE_OVERLAP. Pass start/end/year/quarter to override.
    """
    extra = {}
    if start is not None:
        extra["start_date"] = start
    if end is not None:
        extra["end_date"] = end
    if year is not None:
        extra["year"] = year
    if quarter is not None:
        extra["quarter"] = quarter
    extra.update(overrides)
    payload = create_cycle_payload(**extra)
    resp = api_client.create_cycle(payload, _admin_headers())
    return get_success_data(resp)


def open_cycle(cycle_id):
    resp = api_client.open_cycle(cycle_id, _admin_headers())
    return get_success_data(resp)


def create_open_cycle(**overrides):
    """Create a cycle and open it. Returns the OPEN cycle dict."""
    cycle = create_cycle(**overrides)
    return open_cycle(cycle["id"])


def create_objective(cycle_id, owner_user_id, level="INDIVIDUAL", department_id=None,
                     parent_objective_id=None, weight=1.0, confidential=False,
                     title=None, **overrides):
    """Create a DRAFT objective. Acting role is PlatformAdmin (override role).

    PlatformAdmin can create objectives for any owner_user_id (PRD §3.2 + §2.1
    'admin override').
    """
    payload = {
        "cycle_id": cycle_id,
        "level": level,
        "owner_user_id": owner_user_id,
        "title": title or f"Objective {uuid.uuid4().hex[:6]}",
        "weight": weight,
        "confidential": confidential,
    }
    if department_id is not None:
        payload["department_id"] = department_id
    if parent_objective_id is not None:
        payload["parent_objective_id"] = parent_objective_id
    payload.update(overrides)
    resp = api_client.create_objective(payload, _admin_headers())
    return get_success_data(resp)


def add_kr(objective_id, owner_user_id, payload=None, **kr_overrides):
    """Add a KR to an objective. Acting identity is the OWNER.

    PRD §3.3 — KR mutation is owner-gated; X-User-ID must equal owner_user_id.
    """
    if payload is None:
        payload = create_kr_payload(**kr_overrides)
    resp = api_client.create_key_result(
        objective_id, payload, make_employee_headers(owner_user_id)
    )
    return get_success_data(resp)


def add_numeric_kr(objective_id, owner_user_id, start_value=0, target_value=100, weight=1.0, **overrides):
    payload = create_numeric_kr_payload(
        start_value=start_value, target_value=target_value, weight=weight, **overrides
    )
    return add_kr(objective_id, owner_user_id, payload=payload)


def add_percentage_kr(objective_id, owner_user_id, start_value=0.0, target_value=1.0, weight=1.0, **overrides):
    payload = create_percentage_kr_payload(
        start_value=start_value, target_value=target_value, weight=weight, **overrides
    )
    return add_kr(objective_id, owner_user_id, payload=payload)


def add_milestone_kr(objective_id, owner_user_id, milestones=None, weight=1.0, **overrides):
    payload = create_milestone_kr_payload(
        milestones=milestones, weight=weight, **overrides
    )
    return add_kr(objective_id, owner_user_id, payload=payload)


def publish_objective(objective_id, owner_user_id):
    """PRD §3.2 — DRAFT → ACTIVE; gated to owner (or admin override)."""
    resp = api_client.publish_objective(objective_id, make_employee_headers(owner_user_id))
    return get_success_data(resp)


def post_progress(kr_id, owner_user_id, payload):
    resp = api_client.post_progress(kr_id, payload, make_employee_headers(owner_user_id))
    return get_success_data(resp)


def post_value_change(kr_id, owner_user_id, new_value, comment=None):
    return post_progress(kr_id, owner_user_id, create_value_change_payload(new_value, comment))


def post_milestone_toggle(kr_id, owner_user_id, milestone_index, milestone_completed, comment=None):
    return post_progress(
        kr_id, owner_user_id,
        create_milestone_toggle_payload(milestone_index, milestone_completed, comment),
    )


# ---------------------------------------------------------------------------
# Tier 1 — Standard org (department + employee + manager-of-employee)
# ---------------------------------------------------------------------------

def setup_org():
    """Create one Department, one Employee, one Manager (manager of the Employee).

    Returns dict with: department, manager_user, employee_user, headers.
    The manager_user's id == employee_user.manager_id so manager-only review actions
    will pass the manager-of-owner check (PRD §3.7).
    """
    dept = create_department()
    manager_user = create_user(dept["id"], role_type="MANAGER")
    employee_user = create_user(
        dept["id"], role_type="EMPLOYEE", manager_id=manager_user["id"]
    )
    return {
        "department": dept,
        "manager_user": manager_user,
        "employee_user": employee_user,
        "manager_headers": make_manager_headers(manager_user["id"]),
        "employee_headers": make_employee_headers(employee_user["id"]),
        "admin_headers": _admin_headers(),
        "hrbp_headers": _hrbp_headers(),
    }


# ---------------------------------------------------------------------------
# Tier 2 — Active objective with KRs
# ---------------------------------------------------------------------------

def setup_active_individual_objective(num_krs=1, kr_weights=None, kr_kind="NUMERIC", **objective_overrides):
    """Org → OPEN cycle → INDIVIDUAL objective with N KRs whose weights sum to 1.0 → publish.

    Returns dict with: org, cycle, objective, krs (list of KR dicts).
    """
    org = setup_org()
    cycle = create_open_cycle()
    objective = create_objective(
        cycle["id"],
        org["employee_user"]["id"],
        level="INDIVIDUAL",
        department_id=org["department"]["id"],
        **objective_overrides,
    )
    if kr_weights is None:
        kr_weights = [1.0 / num_krs] * num_krs
    krs = []
    for w in kr_weights:
        if kr_kind == "NUMERIC":
            kr = add_numeric_kr(objective["id"], org["employee_user"]["id"], weight=w)
        elif kr_kind == "PERCENTAGE":
            kr = add_percentage_kr(objective["id"], org["employee_user"]["id"], weight=w)
        elif kr_kind == "MILESTONE":
            kr = add_milestone_kr(objective["id"], org["employee_user"]["id"], weight=w)
        else:
            raise ValueError(f"unknown kr_kind {kr_kind!r}")
        krs.append(kr)
    objective = publish_objective(objective["id"], org["employee_user"]["id"])
    return {"org": org, "cycle": cycle, "objective": objective, "krs": krs}


def setup_objective_with_progress(progress_value=0.5):
    """Active objective with single NUMERIC KR (start=0, target=100), then post a value-change.

    Returns dict with: org, cycle, objective, kr, progress.
    """
    s = setup_active_individual_objective(num_krs=1, kr_kind="NUMERIC")
    kr = s["krs"][0]
    new_value = progress_value * 100  # for start=0 target=100, score = new_value/100
    progress = post_value_change(kr["id"], s["org"]["employee_user"]["id"], new_value)
    s["kr"] = kr
    s["progress"] = progress
    # refresh objective
    resp = api_client.get_objective(s["objective"]["id"], s["org"]["admin_headers"])
    s["objective"] = get_success_data(resp)
    return s


# ---------------------------------------------------------------------------
# Tier 3 — Two-objective alignment scenario
# ---------------------------------------------------------------------------

def setup_alignment_pair(progress_a=0.8, progress_b=0.5, dependency_type="SUPPORTS"):
    """Two ACTIVE INDIVIDUAL objectives A (upstream) and B (downstream), each with one
    NUMERIC KR start=0 target=100. Apply progress so A.progress=progress_a, B.progress=progress_b.
    Returns dict with: org_a, org_b, cycle, objective_a, kr_a, objective_b, kr_b, link.

    The owners are TWO DIFFERENT Employees (A and B) so that the accept-link call from
    B's owner exercises ownership scoping correctly. Acceptor must be B's owner per PRD §3.5.
    """
    org = setup_org()
    cycle = create_open_cycle()

    # Two distinct employees in same department, both reporting to same manager
    employee_a = org["employee_user"]
    employee_b = create_user(
        org["department"]["id"],
        role_type="EMPLOYEE",
        manager_id=org["manager_user"]["id"],
    )

    # Objective A
    obj_a = create_objective(
        cycle["id"], employee_a["id"], level="INDIVIDUAL",
        department_id=org["department"]["id"],
    )
    kr_a = add_numeric_kr(obj_a["id"], employee_a["id"], 0, 100, 1.0)
    obj_a = publish_objective(obj_a["id"], employee_a["id"])
    # Apply progress_a
    if progress_a > 0:
        post_value_change(kr_a["id"], employee_a["id"], progress_a * 100)

    # Objective B
    obj_b = create_objective(
        cycle["id"], employee_b["id"], level="INDIVIDUAL",
        department_id=org["department"]["id"],
    )
    kr_b = add_numeric_kr(obj_b["id"], employee_b["id"], 0, 100, 1.0)
    obj_b = publish_objective(obj_b["id"], employee_b["id"])
    if progress_b > 0:
        post_value_change(kr_b["id"], employee_b["id"], progress_b * 100)

    # Pending link declared by upstream owner
    link_payload = create_alignment_link_payload(obj_a["id"], obj_b["id"], dependency_type)
    link_resp = api_client.create_alignment_link(
        link_payload, make_employee_headers(employee_a["id"])
    )
    link = get_success_data(link_resp)

    # Refresh A and B
    obj_a = get_success_data(api_client.get_objective(obj_a["id"], _admin_headers()))
    obj_b = get_success_data(api_client.get_objective(obj_b["id"], _admin_headers()))

    return {
        "org": org,
        "cycle": cycle,
        "employee_a": employee_a,
        "employee_b": employee_b,
        "objective_a": obj_a,
        "kr_a": kr_a,
        "objective_b": obj_b,
        "kr_b": kr_b,
        "link": link,
    }


def setup_accepted_alignment_pair(progress_a=0.8, progress_b=0.5):
    """Build setup_alignment_pair, then accept the link as B's owner."""
    s = setup_alignment_pair(progress_a=progress_a, progress_b=progress_b)
    resp = api_client.accept_alignment_link(
        s["link"]["id"], make_employee_headers(s["employee_b"]["id"])
    )
    s["link"] = get_success_data(resp)
    return s


# ---------------------------------------------------------------------------
# Tier 4 — Hierarchical (3-level tree: COMPANY > DEPARTMENT > TEAM)
# ---------------------------------------------------------------------------

def setup_three_level_hierarchy():
    """Build COMPANY → DEPARTMENT → TEAM tree where leaf has one NUMERIC KR
    (start=0 target=100, weight=1.0); the two upper levels are pure parent-with-children
    (kr_count=0) so progress rolls up via the §3.4 child-aggregation branch.

    PRD §3.2 requires parent to be ACTIVE at publish time, and the publish branches
    are mutually exclusive (leaf-with-KRs xor parent-with-children). The only PRD-faithful
    way to construct this hierarchy is to bootstrap each upper level with a temporary KR,
    publish, then archive that KR after children are in place — leaving each upper level
    in the parent-with-children state.

    Returns dict with: org, cycle, grandparent (G), parent (P), leaf (L), kr_l.
    """
    org = setup_org()
    cycle = create_open_cycle()

    company_user = create_user(org["department"]["id"], role_type="EMPLOYEE",
                               manager_id=org["manager_user"]["id"])
    dept_user = create_user(org["department"]["id"], role_type="EMPLOYEE",
                            manager_id=org["manager_user"]["id"])
    team_user = create_user(org["department"]["id"], role_type="EMPLOYEE",
                            manager_id=org["manager_user"]["id"])

    # 1. Grandparent: bootstrap with KR, publish, then later archive.
    grandparent = create_objective(
        cycle["id"], company_user["id"], level="COMPANY",
        department_id=org["department"]["id"], weight=1.0,
    )
    kr_g = add_numeric_kr(grandparent["id"], company_user["id"], 0, 100, 1.0)
    grandparent = publish_objective(grandparent["id"], company_user["id"])

    # 2. Parent: created with parent=G (ACTIVE), bootstrap with KR, publish.
    parent = create_objective(
        cycle["id"], dept_user["id"], level="DEPARTMENT",
        department_id=org["department"]["id"],
        parent_objective_id=grandparent["id"], weight=1.0,
    )
    kr_p = add_numeric_kr(parent["id"], dept_user["id"], 0, 100, 1.0)
    parent = publish_objective(parent["id"], dept_user["id"])

    # 3. Leaf: created with parent=P (ACTIVE), real KR, publish.
    leaf = create_objective(
        cycle["id"], team_user["id"], level="TEAM",
        department_id=org["department"]["id"],
        parent_objective_id=parent["id"], weight=1.0,
    )
    kr_l = add_numeric_kr(leaf["id"], team_user["id"], 0, 100, 1.0)
    leaf = publish_objective(leaf["id"], team_user["id"])

    # 4. Now archive the bootstrap KRs so G and P become parent-with-children only.
    api_client.delete_key_result(kr_p["id"], make_employee_headers(dept_user["id"]))
    api_client.delete_key_result(kr_g["id"], make_employee_headers(company_user["id"]))

    # Re-read so callers see post-archive state.
    grandparent = get_success_data(api_client.get_objective(grandparent["id"], _admin_headers()))
    parent = get_success_data(api_client.get_objective(parent["id"], _admin_headers()))
    leaf = get_success_data(api_client.get_objective(leaf["id"], _admin_headers()))

    return {
        "org": org,
        "cycle": cycle,
        "company_user": company_user,
        "dept_user": dept_user,
        "team_user": team_user,
        "grandparent": grandparent,
        "parent": parent,
        "leaf": leaf,
        "kr_l": kr_l,
    }


# ---------------------------------------------------------------------------
# Tier 5 — Review chain (ReviewScore at various states)
# ---------------------------------------------------------------------------

def setup_review_at_pending_self():
    """Active objective → start cycle review → ReviewScore at PENDING_SELF.

    Returns dict with: org, cycle (now IN_REVIEW), objective (now IN_REVIEW), kr,
    review (PENDING_SELF).
    """
    s = setup_active_individual_objective(num_krs=1, kr_kind="NUMERIC")
    # Apply some progress so the review sees a non-zero base
    post_value_change(s["krs"][0]["id"], s["org"]["employee_user"]["id"], 50.0)
    # PlatformAdmin starts review; cycle and objective both transition
    resp = api_client.start_review_cycle(s["cycle"]["id"], _admin_headers())
    s["cycle"] = get_success_data(resp)
    # Refresh objective (now IN_REVIEW)
    s["objective"] = get_success_data(api_client.get_objective(s["objective"]["id"], _admin_headers()))
    # Locate the review for this objective via list with filter
    # ReviewScore has objective_id field; we need to find it. Simplest: list all reviews?
    # No /reviews list endpoint in PRD. Instead use audit-logs or guess via objective.
    # The PRD doesn't expose a /reviews list, but the objective response should ideally
    # carry the review id. Look at GET /reviews/{id} — to get the id we either:
    #   (a) read it from the start-review cascade response data (varies by impl), or
    #   (b) read from an audit log filter.
    # We use audit-logs filtered by entity_type=REVIEW_SCORE and the objective_id
    # is captured in after_value (PRD §2.7).
    # Simpler: most implementations expose the review on the objective response.
    review = _find_review_for_objective(s["objective"]["id"])
    s["review"] = review
    s["kr"] = s["krs"][0]
    return s


def _find_review_for_objective(objective_id):
    """Locate the ReviewScore for an Objective.

    Strategy: query GET /audit-logs filtered to entity_type=REVIEW_SCORE, walk every
    entity_id in the audit history, fetch GET /reviews/{entity_id}, and return the one
    whose objective_id matches. PRD §2.7 guarantees audit logs for ReviewScore CREATE.
    PRD §3.1 guarantees one ReviewScore per Objective per cycle.
    PlatformAdmin and HRBP can read audit logs (PRD §4 endpoint table).
    """
    headers = _admin_headers()
    seen_review_ids = set()
    offset = 0
    limit = 100
    while True:
        params = {"limit": limit, "offset": offset, "entity_type": "REVIEW_SCORE"}
        resp = api_client.list_audit_logs(headers, params=params)
        body = resp.json()
        rows = body.get("data", [])
        for row in rows:
            review_id = row.get("entity_id")
            if not review_id or review_id in seen_review_ids:
                continue
            seen_review_ids.add(review_id)
            review_resp = api_client.get_review(review_id, headers)
            if review_resp.status_code != 200:
                continue
            review = get_success_data(review_resp)
            if review.get("objective_id") == objective_id:
                return review
        meta = body.get("meta", {})
        if not meta.get("has_more"):
            break
        offset += limit
    raise RuntimeError(f"Setup failed: could not locate ReviewScore for objective {objective_id}")


def setup_review_at_pending_manager(self_score=0.6):
    """Build setup_review_at_pending_self → owner self-submits → review at PENDING_MANAGER."""
    s = setup_review_at_pending_self()
    resp = api_client.self_submit_review(
        s["review"]["id"], self_submit_payload(self_score),
        s["org"]["employee_headers"],
    )
    s["review"] = get_success_data(resp)
    return s


def setup_review_at_pending_calibration(self_score=0.6, manager_score=0.5):
    """Pending-manager → manager submits → review at PENDING_CALIBRATION."""
    s = setup_review_at_pending_manager(self_score=self_score)
    resp = api_client.manager_submit_review(
        s["review"]["id"], manager_submit_payload(manager_score),
        s["org"]["manager_headers"],
    )
    s["review"] = get_success_data(resp)
    return s


def setup_locked_review(self_score=0.6, manager_score=0.5, calibration_score=None):
    """Walk all the way to LOCKED.

    If calibration_score is given (and delta > 0.05), HRBP calibrates first; either way HRBP locks.
    """
    s = setup_review_at_pending_calibration(self_score=self_score, manager_score=manager_score)
    if calibration_score is not None:
        resp = api_client.calibrate_review(
            s["review"]["id"], calibrate_payload(calibration_score),
            s["org"]["hrbp_headers"],
        )
        s["review"] = get_success_data(resp)
    resp = api_client.lock_review(s["review"]["id"], s["org"]["hrbp_headers"])
    s["review"] = get_success_data(resp)
    # Refresh objective and cycle
    s["objective"] = get_success_data(api_client.get_objective(s["objective"]["id"], _admin_headers()))
    s["cycle"] = get_success_data(api_client.get_cycle(s["cycle"]["id"], _admin_headers()))
    return s


# ---------------------------------------------------------------------------
# Tier 6 — Specialized recipes from SCAFFOLD_DIFFICULTY_DESIGN
# ---------------------------------------------------------------------------

def setup_dual_variant_objective(self_score=0.7000, manager_score=0.6000, calibration_score=0.4500):
    """Difficulty-design instance: objective_progress_provisional_vs_locked.

    Cycle OPEN; INDIVIDUAL objective with KR1 NUMERIC weight=0.5 (current=50,
    score=0.5000) and KR2 PERCENTAGE weight=0.5 (current=0.8, score=0.8000) →
    Objective.progress = 0.5*0.5 + 0.8*0.5 = 0.6500.
    Then start review, walk through self/manager/calibrate/lock with the supplied scores.

    Returns dict with: org, cycle, objective, kr1, kr2, review.
    """
    org = setup_org()
    cycle = create_open_cycle()
    objective = create_objective(
        cycle["id"], org["employee_user"]["id"], level="INDIVIDUAL",
        department_id=org["department"]["id"],
    )
    kr1 = add_numeric_kr(objective["id"], org["employee_user"]["id"],
                         start_value=0, target_value=100, weight=0.5)
    kr2 = add_percentage_kr(objective["id"], org["employee_user"]["id"],
                            start_value=0.0, target_value=1.0, weight=0.5)
    objective = publish_objective(objective["id"], org["employee_user"]["id"])
    post_value_change(kr1["id"], org["employee_user"]["id"], 50)        # score=0.5000
    post_value_change(kr2["id"], org["employee_user"]["id"], 0.8)       # score=0.8000

    # Start review (cycle → IN_REVIEW)
    cycle = get_success_data(api_client.start_review_cycle(cycle["id"], _admin_headers()))
    objective = get_success_data(api_client.get_objective(objective["id"], _admin_headers()))
    review = _find_review_for_objective(objective["id"])
    return {
        "org": org,
        "cycle": cycle,
        "objective": objective,
        "kr1": kr1,
        "kr2": kr2,
        "review": review,
        "self_score_target": self_score,
        "manager_score_target": manager_score,
        "calibration_score_target": calibration_score,
    }


def setup_objective_with_two_active_krs(weights=(0.4, 0.6), targets=(3, 7)):
    """Difficulty-design instance: objective_progress_round_per_kr_then_sum.

    INDIVIDUAL objective, two NUMERIC KRs with the supplied weights and target_values.
    Returns dict with: org, cycle, objective, kr1, kr2.
    """
    org = setup_org()
    cycle = create_open_cycle()
    objective = create_objective(
        cycle["id"], org["employee_user"]["id"], level="INDIVIDUAL",
        department_id=org["department"]["id"],
    )
    kr1 = add_numeric_kr(objective["id"], org["employee_user"]["id"],
                         start_value=0, target_value=targets[0], weight=weights[0])
    kr2 = add_numeric_kr(objective["id"], org["employee_user"]["id"],
                         start_value=0, target_value=targets[1], weight=weights[1])
    objective = publish_objective(objective["id"], org["employee_user"]["id"])
    return {"org": org, "cycle": cycle, "objective": objective, "kr1": kr1, "kr2": kr2}


def setup_confidential_objective():
    """Active confidential objective owned by employee_owner; reader is a separate
    Employee who is NOT in the access list initially.
    """
    org = setup_org()
    cycle = create_open_cycle()
    reader = create_user(org["department"]["id"], role_type="EMPLOYEE",
                         manager_id=org["manager_user"]["id"])
    objective = create_objective(
        cycle["id"], org["employee_user"]["id"], level="INDIVIDUAL",
        department_id=org["department"]["id"], confidential=True,
    )
    kr = add_numeric_kr(objective["id"], org["employee_user"]["id"], 0, 100, 1.0)
    objective = publish_objective(objective["id"], org["employee_user"]["id"])
    return {
        "org": org,
        "cycle": cycle,
        "reader_user": reader,
        "reader_headers": make_employee_headers(reader["id"]),
        "objective": objective,
        "kr": kr,
    }


def setup_locked_cycle_with_two_objectives_and_link():
    """Difficulty-design instance: cycle_archive_cascade_to_links.

    Cycle in LOCKED with 2 Objectives A, B both LOCKED, plus 1 ACCEPTED AlignmentLink A→B.

    Walks: org → open cycle → 2 published objectives with KRs → start review →
    self/manager submit/lock for each objective → cycle.lock.
    The accepted link is created and accepted while both A and B are still ACTIVE
    (cycle still OPEN), then we transition to IN_REVIEW and on through LOCKED. The
    ACCEPTED link stays ACCEPTED through review → lock; on cycle.archive it should
    transition to BROKEN.
    """
    s = setup_alignment_pair(progress_a=0.5, progress_b=0.5)
    # Accept link first (still in OPEN cycle)
    accept_resp = api_client.accept_alignment_link(
        s["link"]["id"], make_employee_headers(s["employee_b"]["id"])
    )
    s["link"] = get_success_data(accept_resp)
    org = s["org"]
    cycle = s["cycle"]

    # Start review cascade
    cycle = get_success_data(api_client.start_review_cycle(cycle["id"], _admin_headers()))

    # Lock both reviews. Each objective has its own review.
    obj_a = s["objective_a"]
    obj_b = s["objective_b"]
    review_a = _find_review_for_objective(obj_a["id"])
    review_b = _find_review_for_objective(obj_b["id"])

    # Owner self-submits, manager (org["manager_user"]) submits, HRBP locks (no calibration).
    api_client.self_submit_review(review_a["id"], self_submit_payload(0.5),
                                  make_employee_headers(s["employee_a"]["id"]))
    api_client.manager_submit_review(review_a["id"], manager_submit_payload(0.5),
                                     org["manager_headers"])
    api_client.lock_review(review_a["id"], org["hrbp_headers"])

    api_client.self_submit_review(review_b["id"], self_submit_payload(0.5),
                                  make_employee_headers(s["employee_b"]["id"]))
    api_client.manager_submit_review(review_b["id"], manager_submit_payload(0.5),
                                     org["manager_headers"])
    api_client.lock_review(review_b["id"], org["hrbp_headers"])

    # Cycle lock
    cycle = get_success_data(api_client.lock_cycle(cycle["id"], _admin_headers()))

    # Refresh objects
    obj_a = get_success_data(api_client.get_objective(obj_a["id"], _admin_headers()))
    obj_b = get_success_data(api_client.get_objective(obj_b["id"], _admin_headers()))
    link = get_success_data(api_client.list_alignment_links(
        _admin_headers(), params={"upstream_objective_id": obj_a["id"]}
    ))
    # link is a list; we just want our link
    link_resp = api_client.list_alignment_links(_admin_headers(),
                                                params={"upstream_objective_id": obj_a["id"]})
    link_body = link_resp.json()
    our_link = next((l for l in link_body.get("data", []) if l["id"] == s["link"]["id"]), None)
    s["link"] = our_link or s["link"]

    s["cycle"] = cycle
    s["objective_a"] = obj_a
    s["objective_b"] = obj_b
    return s
