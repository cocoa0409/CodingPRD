"""Composite setup helpers — multi-step scenario builders used across tests.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints (the server is restarted before each test). Setup calls use the
lenient get_success_data() so failures surface as clear "Setup failed" errors.

Identity threading: every entity-backed role call uses make_*_headers(entity_id)
built from the freshly created employee record — never the shared constants.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_org_unit_payload,
    create_employee_payload,
    create_coaching_entry_payload,
    create_concern_payload,
    create_pip_template_payload,
    create_pip_payload,
    create_check_in_payload,
    create_mark_held_payload,
    create_evidence_payload,
    create_legal_review_payload,
    submit_legal_review_payload,
    create_outcome_decision_payload,
    create_rebuttal_payload,
    NARRATIVE_A,
    NARRATIVE_B,
)
from .test_users import (
    TEST_USERS,
    make_manager_headers,
    make_hrbp_headers,
    make_counsel_headers,
    make_director_headers,
    make_employee_headers,
)


def _setup_fail(step, resp):
    raise AssertionError(
        f"Setup failed at step {step}: status={resp.status_code} body={resp.text}"
    )


def _ok(resp, step):
    if resp.status_code >= 400:
        _setup_fail(step, resp)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: Entity hierarchy — org unit + cast of employees
# ---------------------------------------------------------------------------

def create_org_unit(name="OU1"):
    """Create an org unit. Returns the org unit dict."""
    resp = api_client.create_org_unit(
        create_org_unit_payload(name=name), TEST_USERS["admin_headers"]
    )
    return _ok(resp, "create_org_unit")


def create_employee(ou_id, **overrides):
    """Create an employee in the org unit. Returns the employee dict."""
    resp = api_client.create_employee(
        ou_id, create_employee_payload(**overrides), TEST_USERS["admin_headers"]
    )
    return _ok(resp, "create_employee")


def setup_cast(email_suffix="x.com"):
    """Org unit plus the standard cast of employees.

    Returns a dict with keys: ou (dict), ou_id, mgr_id, hrbp_id, emp_id.
    """
    ou = create_org_unit()
    ou_id = ou["id"]
    mgr = create_employee(
        ou_id, full_name="Boss M1", email=f"m1@{email_suffix}",
        job_family="ENGINEERING", job_level=6,
    )
    hrbp = create_employee(
        ou_id, full_name="HRBP H1", email=f"h1@{email_suffix}",
        job_family="OPERATIONS", job_level=7,
    )
    emp = create_employee(
        ou_id, full_name="E1 Subject", email=f"e1@{email_suffix}",
        job_family="ENGINEERING", job_level=5, manager_id=mgr["id"],
    )
    return {
        "ou": ou,
        "ou_id": ou_id,
        "mgr_id": mgr["id"],
        "hrbp_id": hrbp["id"],
        "emp_id": emp["id"],
    }


def add_employee(ou_id, full_name, email, job_family="OPERATIONS", job_level=7,
                 manager_id=None):
    payload = create_employee_payload(
        full_name=full_name, email=email, job_family=job_family,
        job_level=job_level,
    )
    if manager_id:
        payload["manager_id"] = manager_id
    resp = api_client.create_employee(ou_id, payload, TEST_USERS["admin_headers"])
    return _ok(resp, f"create_employee({full_name})")


# ---------------------------------------------------------------------------
# Tier 1/2: coaching record + concern progression
# ---------------------------------------------------------------------------

def create_coaching_entries(cast, count=2, severity="DOCUMENTED", category="QUALITY"):
    """Append `count` coaching entries on the subject employee by their manager.

    Returns list of entry ids.
    """
    ids = []
    mgr_headers = make_manager_headers(cast["mgr_id"])
    for i in range(count):
        narrative = NARRATIVE_A if i % 2 == 0 else NARRATIVE_B
        resp = api_client.create_coaching_log_entry(
            cast["ou_id"], cast["emp_id"],
            create_coaching_entry_payload(
                occurred_at=f"2026-07-{1 + i * 7:02d}T10:00:00Z",
                category=category, severity=severity, narrative=narrative,
            ),
            mgr_headers,
        )
        ids.append(_ok(resp, f"create_coaching_entry[{i}]")["id"])
    return ids


def create_and_submit_concern(cast, entry_ids, category="QUALITY",
                              summary="Quality below bar for level"):
    """Raise + submit a concern. Returns concern dict (in SUBMITTED)."""
    mgr_headers = make_manager_headers(cast["mgr_id"])
    resp = api_client.create_concern(
        cast["ou_id"], cast["emp_id"],
        create_concern_payload(entry_ids, category=category, summary=summary),
        mgr_headers,
    )
    concern = _ok(resp, "create_concern")
    resp = api_client.submit_concern(
        cast["ou_id"], cast["emp_id"], concern["id"], mgr_headers
    )
    return _ok(resp, "submit_concern")


def create_and_accept_concern(cast, entry_ids, hrbp_id=None, **kwargs):
    """Raise + submit + accept a concern. Returns concern dict (ACCEPTED)."""
    hrbp_id = hrbp_id or cast["hrbp_id"]
    concern = create_and_submit_concern(cast, entry_ids, **kwargs)
    resp = api_client.accept_concern(
        cast["ou_id"], cast["emp_id"], concern["id"], make_hrbp_headers(hrbp_id)
    )
    return _ok(resp, "accept_concern")


# ---------------------------------------------------------------------------
# Tier 1: template progression
# ---------------------------------------------------------------------------

def create_and_publish_template(cast, hrbp_id=None, **overrides):
    """Create + publish a PIP template. Returns template dict (PUBLISHED)."""
    hrbp_id = hrbp_id or cast["hrbp_id"]
    hrbp_headers = make_hrbp_headers(hrbp_id)
    resp = api_client.create_pip_template(
        cast["ou_id"], create_pip_template_payload(**overrides), hrbp_headers
    )
    tpl = _ok(resp, "create_pip_template")
    resp = api_client.publish_pip_template(cast["ou_id"], tpl["id"], hrbp_headers)
    return _ok(resp, "publish_pip_template")


# ---------------------------------------------------------------------------
# Tier 3: PIP lifecycle shortcuts
# ---------------------------------------------------------------------------

def setup_concern_and_template(cast, hrbp_id=None, **template_overrides):
    """Two DOCUMENTED coaching entries + ACCEPTED concern + PUBLISHED template.

    Returns (concern, template).
    """
    entry_ids = create_coaching_entries(cast, count=2)
    concern = create_and_accept_concern(cast, entry_ids, hrbp_id=hrbp_id)
    template = create_and_publish_template(cast, hrbp_id=hrbp_id, **template_overrides)
    return concern, template


def create_draft_pip(cast, concern_id, template_id, hrbp_id=None,
                     start_date="2026-08-01T00:00:00Z"):
    """Create a PIP in DRAFT. Returns the PIP dict."""
    hrbp_id = hrbp_id or cast["hrbp_id"]
    resp = api_client.create_pip(
        cast["ou_id"], cast["emp_id"],
        create_pip_payload(concern_id, template_id, start_date=start_date),
        make_hrbp_headers(hrbp_id),
    )
    return _ok(resp, "create_pip")


def create_and_issue_pip(cast, concern_id, template_id, hrbp_id=None,
                         start_date="2026-08-01T00:00:00Z"):
    """Create + issue a PIP. Returns the issued PIP dict (post-issue GET shape)."""
    hrbp_id = hrbp_id or cast["hrbp_id"]
    pip = create_draft_pip(cast, concern_id, template_id, hrbp_id, start_date)
    resp = api_client.issue_pip(
        cast["ou_id"], cast["emp_id"], pip["id"],
        {"expected_pip_version": pip["version"]},
        make_hrbp_headers(hrbp_id),
    )
    return _ok(resp, "issue_pip")


def setup_issued_pip(cast=None, hrbp_id=None, start_date="2026-08-01T00:00:00Z",
                     **template_overrides):
    """Full pipeline through ISSUED: cast + concern + template + PIP issued.

    Returns dict with cast entries plus: concern_id, template_id, pip (dict).
    """
    cast = cast or setup_cast()
    concern, template = setup_concern_and_template(
        cast, hrbp_id=hrbp_id, **template_overrides
    )
    pip = create_and_issue_pip(
        cast, concern["id"], template["id"], hrbp_id=hrbp_id,
        start_date=start_date,
    )
    return {
        **cast,
        "concern_id": concern["id"],
        "template_id": template["id"],
        "pip": pip,
        "pip_id": pip["id"],
    }


def setup_active_pip(cast=None, scheduled_for="2026-08-11T00:00:00Z",
                     clock_to=None, **template_overrides):
    """PIP ISSUED + one SCHEDULED check-in + clock advanced so the plan is ACTIVE.

    Default: start_date 2026-08-01, clock advanced to 2026-08-11T10:00:00Z.
    Returns dict from setup_issued_pip plus check_in_id.
    """
    ctx = setup_issued_pip(cast=cast, **template_overrides)
    hrbp_headers = make_hrbp_headers(ctx["hrbp_id"])
    resp = api_client.create_check_in(
        ctx["ou_id"], ctx["emp_id"], ctx["pip_id"],
        create_check_in_payload(scheduled_for=scheduled_for),
        hrbp_headers,
    )
    ctx["check_in_id"] = _ok(resp, "create_check_in")["id"]
    clock_to = clock_to or "2026-08-11T10:00:00Z"
    set_clock(ctx["ou_id"], clock_to)
    return ctx


def set_clock(ou_id, to_iso8601):
    resp = api_client.set_clock(
        ou_id, {"to_iso8601": to_iso8601}, TEST_USERS["admin_headers"]
    )
    return _ok(resp, f"set_clock({to_iso8601})")


def get_pip(ctx):
    resp = api_client.get_pip(
        ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], make_hrbp_headers(ctx["hrbp_id"])
    )
    return _ok(resp, "get_pip")


def get_employee(ctx):
    resp = api_client.get_employee(
        ctx["ou_id"], ctx["emp_id"], make_hrbp_headers(ctx["hrbp_id"])
    )
    return _ok(resp, "get_employee")


def get_goals(ctx):
    resp = api_client.list_pip_goals(
        ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], make_hrbp_headers(ctx["hrbp_id"])
    )
    return _ok(resp, "list_pip_goals")


# ---------------------------------------------------------------------------
# Tier 4: evidence + held check-in scenarios
# ---------------------------------------------------------------------------

def ensure_second_hrbp(ctx):
    """Return the id of a second HRBP in the org unit (created on demand).

    PRD §3.4 segregation of duties: "evidence submitted by the issuing HRBP
    must be adjudicated by a different HRBP".
    """
    if "hrbp2_id" not in ctx:
        hrbp2 = add_employee(ctx["ou_id"], "HRBP H2", "h2.second@x.com",
                             job_family="OPERATIONS", job_level=7)
        ctx["hrbp2_id"] = hrbp2["id"]
    return ctx["hrbp2_id"]


def submit_and_adjudicate_evidence(ctx, check_in_id, goal_id, observed_value,
                                   adjudicator_hrbp_id=None, source="SYSTEM_REPORT",
                                   admit=True, submitter_hrbp_id=None):
    """Submit one evidence item and adjudicate it. Returns evidence dict.

    The default submitter is the plan's issuing HRBP, so per PRD §3.4 the
    default adjudicator is a *different* HRBP (created on demand).
    """
    submitter = submitter_hrbp_id or ctx["hrbp_id"]
    resp = api_client.submit_evidence(
        ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], check_in_id,
        create_evidence_payload(goal_id, observed_value=observed_value, source=source),
        make_hrbp_headers(submitter),
    )
    ev = _ok(resp, "submit_evidence")
    adjudicator = adjudicator_hrbp_id or ensure_second_hrbp(ctx)
    if admit:
        resp = api_client.admit_evidence(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], check_in_id, ev["id"],
            make_hrbp_headers(adjudicator),
        )
    else:
        resp = api_client.exclude_evidence(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], check_in_id, ev["id"],
            make_hrbp_headers(adjudicator),
        )
    return _ok(resp, "adjudicate_evidence")


def hold_check_in(ctx, check_in_id, notes="Reviewed trajectory against goals."):
    resp = api_client.mark_check_in_held(
        ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], check_in_id,
        create_mark_held_payload(notes=notes),
        make_hrbp_headers(ctx["hrbp_id"]),
    )
    return _ok(resp, "mark_check_in_held")


# ---------------------------------------------------------------------------
# Tier 5: legal review + outcome decision scenarios
# ---------------------------------------------------------------------------

def create_and_submit_legal_review(ctx, counsel_id=None, hrbp_id=None, **overrides):
    """Request + claim + submit a legal review. Returns the submitted review dict."""
    hrbp_id = hrbp_id or ctx["hrbp_id"]
    counsel_id = counsel_id or ctx.get("counsel_id")
    if counsel_id is None:
        counsel = add_employee(
            ctx["ou_id"], "Counsel L1", "l1@x.com", job_level=8
        )
        counsel_id = counsel["id"]
        ctx["counsel_id"] = counsel_id
    hrbp_headers = make_hrbp_headers(hrbp_id)
    resp = api_client.create_legal_review(
        ctx["ou_id"], ctx["emp_id"], ctx["pip_id"],
        create_legal_review_payload(counsel_id),
        hrbp_headers,
    )
    review = _ok(resp, "create_legal_review")
    resp = api_client.claim_legal_review(
        ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], review["id"],
        make_counsel_headers(counsel_id),
    )
    _ok(resp, "claim_legal_review")
    resp = api_client.submit_legal_review(
        ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], review["id"],
        submit_legal_review_payload(**overrides),
        make_counsel_headers(counsel_id),
    )
    return _ok(resp, "submit_legal_review")


def propose_outcome(ctx, proposed_outcome, rationale=None, proposer_hrbp_id=None):
    """Propose an outcome decision. Returns the raw response (caller validates)."""
    proposer = proposer_hrbp_id or ctx.get("hrbp_proposer_id") or ctx["hrbp_id"]
    payload = create_outcome_decision_payload(proposed_outcome=proposed_outcome)
    if rationale:
        payload["rationale"] = rationale
    return api_client.create_outcome_decision(
        ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], payload,
        make_hrbp_headers(proposer),
    )


def approve_outcome(ctx, decision_id, director_id=None):
    """Approve an outcome decision with the live pip version. Returns response."""
    director_id = director_id or ctx.get("director_id")
    if director_id is None:
        director = add_employee(
            ctx["ou_id"], "Director D1", "d1@x.com", job_level=9
        )
        director_id = director["id"]
        ctx["director_id"] = director_id
    pip = get_pip(ctx)
    return api_client.approve_outcome_decision(
        ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], decision_id,
        {"expected_pip_version": pip["version"]},
        make_director_headers(director_id),
    )


def setup_pip_ready_for_outcome(outcome="TERMINATION", with_legal=True,
                                attainment_value=None, target_value=2):
    """Full scenario: ACTIVE plan, clock moved past end_date, optional submitted
    legal review, optional admitted evidence to control final attainment.

    Returns ctx dict with decision prerequisites satisfied for proposing.
    """
    ctx = setup_active_pip()
    hrbp_id = ctx["hrbp_id"]
    if attainment_value is not None:
        goals = get_goals(ctx)
        goal_id = goals[0]["id"]
        submit_and_adjudicate_evidence(
            ctx, ctx["check_in_id"], goal_id, attainment_value
        )
        hold_check_in(ctx, ctx["check_in_id"])
    if with_legal:
        create_and_submit_legal_review(ctx, hrbp_id=hrbp_id)
    set_clock(ctx["ou_id"], "2026-09-01T00:00:00Z")
    return ctx
