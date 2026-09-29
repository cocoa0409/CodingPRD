"""Composite state builders and pytest fixtures.

The harness restarts the server and empties the database before every test, so
every helper here builds its state from scratch through PRD-declared endpoints
only. Nothing is shared between tests.
"""
from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import ApiClient
from .constants import TEST_DEFAULTS
from .test_users import (
    make_agency_officer_headers,
    make_auditor_headers,
    make_certifier_headers,
    make_portal_admin_headers,
    make_preparer_headers,
)

ADMIN = make_portal_admin_headers()
OFFICER = make_agency_officer_headers("officer-anna")
OFFICER_2 = make_agency_officer_headers("officer-bram")
AUDITOR = make_auditor_headers("auditor-cruz")
AUDITOR_2 = make_auditor_headers("auditor-dale")


# --------------------------------------------------------------------------
# Low-level builders. Each returns the created resource body.
# --------------------------------------------------------------------------
def move_clock(api: ApiClient, to_iso8601: str) -> dict:
    return get_success_data(api.set_clock(to_iso8601, ADMIN))


def build_portal(api: ApiClient, **overrides) -> dict:
    return get_success_data(
        api.create_reporting_portal(factories.reporting_portal_payload(**overrides), ADMIN),
        expected_status=201,
    )


def build_determination(api: ApiClient, **overrides) -> dict:
    return get_success_data(
        api.create_wage_determination(factories.wage_determination_payload(**overrides), ADMIN),
        expected_status=201,
    )


def build_rate(api: ApiClient, determination_id: str, **overrides) -> dict:
    return get_success_data(
        api.add_wage_rate(determination_id, factories.wage_rate_payload(**overrides), ADMIN),
        expected_status=201,
    )


def activate_determination(api: ApiClient, determination_id: str, **payload) -> dict:
    return get_success_data(api.activate_wage_determination(determination_id, ADMIN, payload))


def build_active_determination(api: ApiClient, rates=None, **overrides):
    """DRAFT determination + its rate rows + activation. Returns (determination, [rates])."""
    determination = build_determination(api, **overrides)
    rate_specs = rates if rates is not None else [{}]
    rate_rows = [build_rate(api, determination["id"], **spec) for spec in rate_specs]
    determination = activate_determination(api, determination["id"])
    return determination, rate_rows


def build_program(api: ApiClient, **overrides) -> dict:
    return get_success_data(
        api.create_apprentice_program(factories.apprentice_program_payload(**overrides), ADMIN),
        expected_status=201,
    )


def build_contractor(api: ApiClient, **overrides) -> dict:
    return get_success_data(
        api.create_contractor(factories.contractor_payload(**overrides), ADMIN),
        expected_status=201,
    )


def build_staff(api: ApiClient, contractor_id: str, **overrides) -> dict:
    return get_success_data(
        api.add_staff(contractor_id, factories.staff_payload(**overrides), ADMIN),
        expected_status=201,
    )


def build_contractor_with_staff(api: ApiClient, **overrides):
    """Contractor plus two distinct staff rows so segregation of duties is satisfiable.

    Returns (contractor, preparer_staff, certifier_staff).
    """
    contractor = build_contractor(api, **overrides)
    preparer = build_staff(api, contractor["id"], full_name="Pat Preparer", capability="PREPARER")
    certifier = build_staff(api, contractor["id"], full_name="Cora Certifier", capability="CERTIFIER")
    return contractor, preparer, certifier


def build_fringe_plan(api: ApiClient, contractor_id: str, preparer_headers: dict, **overrides) -> dict:
    return get_success_data(
        api.create_fringe_plan(contractor_id, factories.fringe_plan_payload(**overrides), preparer_headers),
        expected_status=201,
    )


def rule_on_fringe_plan(api: ApiClient, plan_id: str, target_status: str, headers: dict) -> dict:
    """Rules on a plan, driving ``approval_status`` to APPROVED or REJECTED.

    PRD 3.3 pins the resulting `approval_status` but not the spelling of the `decision`
    literal, so the past-participle form is tried first and the bare verb second. The
    resulting status is asserted, which is the part the specification actually fixes.
    """
    bare_verb = {"APPROVED": "APPROVE", "REJECTED": "REJECT"}[target_status]
    for literal in (target_status, bare_verb):
        resp = api.approve_fringe_plan(plan_id, {"decision": literal}, headers)
        if resp.status_code == 200:
            plan = get_success_data(resp)
            assert plan["approval_status"] == target_status
            return plan
    raise AssertionError(
        f"neither decision literal was accepted for plan {plan_id}: {resp.status_code} {resp.text}"
    )


def build_project(api: ApiClient, determination_id: str, portal_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_project(
            factories.project_payload(determination_id, portal_id, **overrides), ADMIN
        ),
        expected_status=201,
    )


def build_assignment(api: ApiClient, project_id: str, contractor_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_contract_assignment(
            project_id, factories.contract_assignment_payload(contractor_id, **overrides), ADMIN
        ),
        expected_status=201,
    )


def activate_assignment(api: ApiClient, assignment_id: str) -> dict:
    return get_success_data(api.activate_contract_assignment(assignment_id, ADMIN))


def set_project_status(api: ApiClient, project_id: str, to_status: str) -> dict:
    return get_success_data(api.set_project_status(project_id, {"to_status": to_status}, ADMIN))


def build_worker(api: ApiClient, contractor_id: str, preparer_headers: dict, **overrides) -> dict:
    return get_success_data(
        api.create_worker(factories.worker_payload(contractor_id, **overrides), preparer_headers),
        expected_status=201,
    )


def read_assignment(api: ApiClient, assignment_id: str) -> dict:
    return get_success_data(api.get_contract_assignment(assignment_id, ADMIN))


def build_submission(api: ApiClient, env: dict, **overrides) -> dict:
    """Opens a DRAFT payroll, always quoting the tier's freshly re-read version."""
    assignment = read_assignment(api, env["assignment"]["id"])
    payload = factories.payroll_submission_payload(
        assignment["id"], env["preparer"]["id"], assignment["version"], **overrides
    )
    return get_success_data(
        api.create_payroll_submission(payload, env["preparer_headers"]), expected_status=201
    )


def build_line(api: ApiClient, env: dict, submission_id: str, worker_id: str, **overrides) -> dict:
    return get_success_data(
        api.add_payroll_line(
            submission_id, factories.payroll_line_payload(worker_id, **overrides),
            env["preparer_headers"],
        ),
        expected_status=201,
    )


def finalize(api: ApiClient, env: dict, submission_id: str) -> dict:
    return get_success_data(api.finalize_payroll_submission(submission_id, env["preparer_headers"]))


def certify(api: ApiClient, env: dict, submission_id: str, **payload) -> dict:
    return get_success_data(
        api.certify_payroll_submission(submission_id, env["certifier_headers"], payload)
    )


def begin_review(api: ApiClient, submission_id: str, headers: dict = OFFICER) -> dict:
    return get_success_data(api.begin_review_payroll_submission(submission_id, headers))


def accept(api: ApiClient, submission_id: str, headers: dict = OFFICER) -> dict:
    return get_success_data(api.accept_payroll_submission(submission_id, headers))


def build_finding(api: ApiClient, project_id: str, submission_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_finding(factories.finding_payload(project_id, submission_id, **overrides), AUDITOR),
        expected_status=201,
    )


def build_payment(api: ApiClient, env: dict, finding_id: str, worker_id: str, amount_cents: int) -> dict:
    return get_success_data(
        api.create_restitution_payment(
            finding_id, factories.restitution_payment_payload(worker_id, amount_cents),
            env["preparer_headers"],
        ),
        expected_status=201,
    )


def build_interview(api: ApiClient, env: dict, worker_id: str, window_start, window_end, **overrides) -> dict:
    return get_success_data(
        api.create_interview(
            factories.interview_payload(
                env["project"]["id"], env["assignment"]["id"], worker_id,
                window_start, window_end, **overrides,
            ),
            AUDITOR,
        ),
        expected_status=201,
    )


# --------------------------------------------------------------------------
# The canonical composite environment.
# --------------------------------------------------------------------------
def setup_env(
    api: ApiClient,
    rates=None,
    portal_overrides=None,
    determination_overrides=None,
    project_overrides=None,
    assignment_overrides=None,
    activate_project: bool = True,
    with_program=None,
) -> dict:
    """Portal, ACTIVE determination with rate rows, contractor with two staff rows,
    project locked to that determination and portal, prime tier ACTIVE, project ACTIVE.

    ``rates`` is a list of wage_rate_payload override dicts; the first entry is
    exposed as env["rate"]. ``with_program`` (a dict of apprentice_program_payload
    overrides, possibly empty) additionally registers a program as env["program"].
    """
    portal = build_portal(api, **(portal_overrides or {}))
    determination, rate_rows = build_active_determination(
        api, rates=rates, **(determination_overrides or {})
    )
    program = build_program(api, **with_program) if with_program is not None else None
    contractor, preparer, certifier = build_contractor_with_staff(api)
    project = build_project(
        api, determination["id"], portal["id"], **(project_overrides or {})
    )
    assignment = build_assignment(
        api, project["id"], contractor["id"], **(assignment_overrides or {})
    )
    assignment = activate_assignment(api, assignment["id"])
    if activate_project:
        project = set_project_status(api, project["id"], "ACTIVE")
    return {
        "portal": portal,
        "determination": determination,
        "rates": rate_rows,
        "rate": rate_rows[0] if rate_rows else None,
        "program": program,
        "contractor": contractor,
        "preparer": preparer,
        "certifier": certifier,
        "preparer_headers": make_preparer_headers(preparer["id"]),
        "certifier_headers": make_certifier_headers(certifier["id"]),
        "project": project,
        "assignment": assignment,
    }


def setup_env_with_worker(api: ApiClient, worker_overrides=None, **kwargs) -> dict:
    """setup_env plus one journeyworker registered under the tier's contractor."""
    env = setup_env(api, **kwargs)
    env["worker"] = build_worker(
        api, env["contractor"]["id"], env["preparer_headers"], **(worker_overrides or {})
    )
    return env


def compliant_paid_line(**overrides) -> dict:
    """Line overrides that pay the default BASE rate exactly, so the line is compliant."""
    payload = {
        "straight_hours": 40.00,
        "overtime_hours": 0.00,
        "base_rate_paid_cents": TEST_DEFAULTS["BASE_HOURLY_RATE_CENTS"],
        "fringe_cash_paid_cents": TEST_DEFAULTS["FRINGE_HOURLY_RATE_CENTS"],
    }
    payload.update(overrides)
    return payload


def setup_finalized_submission(api: ApiClient, lines=None, week_ending_date=None, **kwargs):
    """setup_env_with_worker, one submission carrying ``lines``, finalized.

    ``lines`` is a list of payroll_line_payload override dicts; each is attached to
    its own freshly registered worker unless the dict carries a "worker_id".
    Returns (env, submission, [line rows]).
    """
    env = setup_env(api, **kwargs)
    week = week_ending_date or TEST_DEFAULTS["WEEK_ENDING_DATE"]
    submission = build_submission(api, env, week_ending_date=week)
    specs = lines if lines is not None else [compliant_paid_line()]
    rows = []
    for spec in specs:
        spec = dict(spec)
        worker_id = spec.pop("worker_id", None)
        if worker_id is None:
            worker_id = build_worker(api, env["contractor"]["id"], env["preparer_headers"])["id"]
        rows.append(build_line(api, env, submission["id"], worker_id, **spec))
    move_clock(api, week)
    submission = finalize(api, env, submission["id"])
    return env, submission, rows


def setup_accepted_submission(api: ApiClient, lines=None, week_ending_date=None, **kwargs):
    """A compliant weekly payroll carried all the way to workflow_status ACCEPTED.

    Returns (env, submission, [line rows]).
    """
    env, submission, rows = setup_finalized_submission(
        api, lines=lines, week_ending_date=week_ending_date, **kwargs
    )
    certify(api, env, submission["id"])
    begin_review(api, submission["id"])
    submission = accept(api, submission["id"])
    return env, submission, rows


ZERO_PAID_LINE = {
    "straight_hours": 40.00,
    "overtime_hours": 0.00,
    "base_rate_paid_cents": 0,
    "overtime_rate_paid_cents": 0,
    "fringe_cash_paid_cents": 0,
}


def setup_deficient_submission_under_review(
    api: ApiClient, week_ending_date="2026-08-01T00:00:00.000Z", **kwargs
):
    """Two 0-pay journeyworker lines of 40.00 h against a 5000+2000 rate.

    make_whole_underpayment_cents is 560000 and the filing sits in UNDER_REVIEW, because a
    DEFICIENT payroll cannot be accepted. Returns (env, submission, [line rows]).
    """
    env, submission, rows = setup_finalized_submission(
        api,
        lines=[dict(ZERO_PAID_LINE), dict(ZERO_PAID_LINE)],
        week_ending_date=week_ending_date,
        **dict({"rates": [{"fringe_hourly_rate_cents": 2000}]}, **kwargs),
    )
    certify(api, env, submission["id"])
    submission = begin_review(api, submission["id"])
    return env, submission, rows


def setup_proposed_contractor_with_invited_tier(api: ApiClient):
    """Drives one contractor CLEAR -> PROPOSED while it still holds an INVITED tier.

    Project P1 carries an ACCEPTED, COMPLIANT payroll and then three findings worth
    40 + 15 + 15 = 70 risk points, which is the inclusive debarment-proposal threshold.
    Project P2's tier is created while the firm is still CLEAR and is never activated, and
    because a proposal suspends only ACTIVE tiers it stays INVITED.

    Returns a dict with "contractor", "p1", "p2_project" and "invited_assignment".
    """
    p1, p2 = setup_two_project_env(api)
    invited = build_assignment(api, p2["project"]["id"], p1["contractor"]["id"])
    worker = build_worker(api, p1["contractor"]["id"], p1["preparer_headers"])
    submission = build_submission(api, p1, week_ending_date="2026-08-01T00:00:00.000Z")
    build_line(
        api, p1, submission["id"], worker["id"],
        straight_hours=40.00, overtime_hours=0.00,
        base_rate_paid_cents=5000, overtime_rate_paid_cents=0, fringe_cash_paid_cents=2000,
    )
    move_clock(api, "2026-08-01T00:00:00.000Z")
    finalize(api, p1, submission["id"])
    certify(api, p1, submission["id"])
    begin_review(api, submission["id"])
    accept(api, submission["id"])
    for finding_type, severity in (
        ("UNDERPAYMENT", "CRITICAL"),
        ("FRINGE_CREDIT", "MAJOR"),
        ("MISCLASSIFICATION", "MAJOR"),
    ):
        build_finding(
            api, p1["project"]["id"], submission["id"],
            finding_type=finding_type, severity=severity, restitution_required_cents=0,
        )
    return {
        "contractor": get_success_data(api.get_contractor(p1["contractor"]["id"], ADMIN)),
        "p1": p1,
        "p2_project": p2["project"],
        "invited_assignment": invited,
    }


def setup_env_single_both_staff(api: ApiClient, **kwargs) -> dict:
    """setup_env, but the contractor carries exactly one staff row whose capability is BOTH.

    ``preparer`` and ``certifier`` are therefore the same row, so segregation of duties can
    never be satisfied on this contractor.
    """
    env = setup_env(api, **kwargs)
    both = build_staff(api, env["contractor"]["id"], full_name="Sam Solo", capability="BOTH")
    env["preparer"] = both
    env["certifier"] = both
    env["preparer_headers"] = make_preparer_headers(both["id"])
    env["certifier_headers"] = make_certifier_headers(both["id"])
    return env


def setup_two_project_env(api: ApiClient):
    """One contractor holding ACTIVE prime tiers on two ACTIVE projects P1 and P2.

    Both projects lock the same portal and the same ACTIVE determination in CA-ALAMEDA.
    Returns (p1_env, p2_env); the two dicts share portal, determination, contractor and
    staff, and differ in "project" and "assignment".
    """
    portal = build_portal(api)
    determination, rate_rows = build_active_determination(
        api, rates=[{"fringe_hourly_rate_cents": 2000}]
    )
    contractor, preparer, certifier = build_contractor_with_staff(api)
    common = {
        "portal": portal,
        "determination": determination,
        "rates": rate_rows,
        "rate": rate_rows[0],
        "program": None,
        "contractor": contractor,
        "preparer": preparer,
        "certifier": certifier,
        "preparer_headers": make_preparer_headers(preparer["id"]),
        "certifier_headers": make_certifier_headers(certifier["id"]),
    }
    envs = []
    for _ in range(2):
        project = build_project(api, determination["id"], portal["id"])
        assignment = activate_assignment(
            api, build_assignment(api, project["id"], contractor["id"])["id"]
        )
        project = set_project_status(api, project["id"], "ACTIVE")
        envs.append(dict(common, project=project, assignment=assignment))
    return envs[0], envs[1]
