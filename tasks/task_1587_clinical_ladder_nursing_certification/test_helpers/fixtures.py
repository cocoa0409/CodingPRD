"""Composite setup helpers.

Every fixture builds its preconditions from scratch through the PRD-declared
endpoints (the server restarts with an empty database before each test).
Setup calls use get_success_data() so failures surface as clear "Setup failed"
errors rather than confusing assertion failures.

Identity threading: Nurse is an entity-backed role, so every ownership-gated
call uses make_nurse_headers(nurse["id"]) with the real record id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_ISO, TEST_DEFAULTS
from .factories import (
    create_anniversary_review_payload,
    create_application_payload,
    create_budget_line_payload,
    create_certification_payload,
    create_ladder_criterion_payload,
    create_nurse_payload,
    create_participation_event_payload,
    create_reimbursement_claim_payload,
    decide_payload,
    score_payload,
    set_clock_payload,
)
from .test_users import TEST_USERS, make_nurse_headers

ADMIN = TEST_USERS["program_admin_headers"]
PAYROLL = TEST_USERS["payroll_officer_headers"]


# ---------------------------------------------------------------------------
# Tier 0: clock + primitive creators
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str = DEFAULT_CLOCK_ISO):
    """Pin the logical clock (PRD §2.5)."""
    get_success_data(api_client.set_current_utc(set_clock_payload(to_iso8601), ADMIN))


def run_ops_cycle() -> dict:
    """Run the ops sweep (PRD §2.9); returns the tally object."""
    return get_success_data(api_client.run_ops_cycle(ADMIN))


def create_nurse(
    employee_code: str,
    full_name: str = "Test Nurse",
    hire_date: str = TEST_DEFAULTS["HIRE_DATE"],
    home_unit: str = TEST_DEFAULTS["HOME_UNIT"],
) -> dict:
    resp = api_client.create_nurse(
        create_nurse_payload(
            employee_code=employee_code,
            full_name=full_name,
            hire_date=hire_date,
            home_unit=home_unit,
        ),
        ADMIN,
    )
    return get_success_data(resp)


def get_nurse(nurse_id: str) -> dict:
    return get_success_data(api_client.get_nurse(nurse_id, ADMIN))


def create_criterion(
    target_level: str = "CN_II",
    min_portfolio_score: int = TEST_DEFAULTS["MIN_PORTFOLIO_SCORE"],
    min_participation_points: int = 0,
    required_certification_track: str = "NONE",
    differential_monthly_cents: int = TEST_DEFAULTS["DIFFERENTIAL_CN_II_CENTS"],
    effective_from: str = TEST_DEFAULTS["CRITERION_EFFECTIVE_FROM"],
    effective_until=None,
) -> dict:
    resp = api_client.create_ladder_criterion(
        create_ladder_criterion_payload(
            target_level=target_level,
            min_portfolio_score=min_portfolio_score,
            min_participation_points=min_participation_points,
            required_certification_track=required_certification_track,
            differential_monthly_cents=differential_monthly_cents,
            effective_from=effective_from,
            effective_until=effective_until,
        ),
        ADMIN,
    )
    return get_success_data(resp)


def create_budget_line(
    unit: str = TEST_DEFAULTS["HOME_UNIT"],
    fiscal_year: int = 2027,
    allocated_cents: int = TEST_DEFAULTS["BUDGET_ALLOCATED_CENTS"],
) -> dict:
    resp = api_client.create_budget_line(
        create_budget_line_payload(
            unit=unit, fiscal_year=fiscal_year, allocated_cents=allocated_cents
        ),
        ADMIN,
    )
    return get_success_data(resp)


def get_budget_line(budget_line_id: str) -> dict:
    return get_success_data(api_client.get_budget_line(budget_line_id, ADMIN))


def create_participation_event(
    nurse_id: str,
    event_kind: str = "QI_PROJECT",
    points: int = 5,
    occurred_on: str = "2026-01-15T00:00:00Z",
) -> dict:
    resp = api_client.create_participation_event(
        create_participation_event_payload(
            nurse_id=nurse_id, event_kind=event_kind,
            points=points, occurred_on=occurred_on,
        ),
        make_nurse_headers(nurse_id),
    )
    return get_success_data(resp)


def verify_event(event_id: str) -> dict:
    return get_success_data(api_client.verify_participation_event(event_id, ADMIN))


def add_verified_points(nurse_id: str, points: int, occurred_on: str,
                        event_kind: str = "QI_PROJECT") -> dict:
    """Create a participation event and verify it. Returns the event."""
    event = create_participation_event(nurse_id, event_kind, points, occurred_on)
    return verify_event(event["id"])


def create_certification(
    nurse_id: str,
    track: str = "BASIC",
    exam_fee_cents: int = TEST_DEFAULTS["EXAM_FEE_CENTS"],
    obtained_on: str = "2026-01-01T00:00:00Z",
    expires_on: str = "2031-01-01T00:00:00Z",
    certifying_body: str = "ANCC",
    renewal_of_id=None,
) -> dict:
    payload = create_certification_payload(
        nurse_id=nurse_id,
        track=track,
        certifying_body=certifying_body,
        exam_fee_cents=exam_fee_cents,
        obtained_on=obtained_on,
        expires_on=expires_on,
    )
    if renewal_of_id is not None:
        payload["renewal_of_id"] = renewal_of_id
    return get_success_data(api_client.create_certification(payload, ADMIN))


def get_certification(certification_id: str) -> dict:
    return get_success_data(api_client.get_certification(certification_id, ADMIN))


def list_bonuses(certification_id: str) -> list:
    return get_success_data(
        api_client.list_certification_bonuses(certification_id, ADMIN)
    )


def get_accrued_bonus(certification_id: str) -> dict:
    """Fetch the bonus row accrued by certification registration (PRD §3.3)."""
    bonuses = list_bonuses(certification_id)
    assert len(bonuses) >= 1, "Setup failed: certification accrued no bonus row"
    return bonuses[0]


def create_claim(certification_id: str, nurse_id: str,
                 claimed_amount_cents: int = 30000) -> dict:
    resp = api_client.create_reimbursement_claim(
        create_reimbursement_claim_payload(
            certification_id=certification_id,
            claimed_amount_cents=claimed_amount_cents,
        ),
        make_nurse_headers(nurse_id),
    )
    return get_success_data(resp)


def approve_claim(claim_id: str, admin_headers=None) -> dict:
    return get_success_data(
        api_client.approve_reimbursement_claim(claim_id, admin_headers or ADMIN)
    )


def pay_claim(claim_id: str) -> dict:
    return get_success_data(api_client.pay_reimbursement_claim(claim_id, PAYROLL))


def create_anniversary_review(nurse_id: str, review_year: int = 2026) -> dict:
    resp = api_client.create_anniversary_review(
        create_anniversary_review_payload(nurse_id=nurse_id, review_year=review_year),
        ADMIN,
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1-3: application state progression and committee flow
# ---------------------------------------------------------------------------

def create_draft_application(nurse: dict, target_level: str = "CN_II",
                             narrative: str = "portfolio") -> dict:
    """Draft an application with the nurse's CURRENT version as the OCC token."""
    nurse_now = get_nurse(nurse["id"])
    resp = api_client.create_application(
        create_application_payload(
            nurse_id=nurse["id"],
            target_level=target_level,
            portfolio_narrative=narrative,
            expected_nurse_version=nurse_now["version"],
        ),
        make_nurse_headers(nurse["id"]),
    )
    return get_success_data(resp)


def submit_application(application: dict, nurse_id: str) -> dict:
    return get_success_data(
        api_client.submit_application(application["id"], make_nurse_headers(nurse_id))
    )


def create_reviewers(count: int = 3, home_unit: str = TEST_DEFAULTS["HOME_UNIT"],
                     code_prefix: str = "RN-REV") -> list:
    """Create `count` distinct reviewer nurses. Returns list of nurse dicts."""
    reviewers = []
    for i in range(count):
        reviewers.append(
            create_nurse(
                employee_code=f"{code_prefix}-{i + 1}",
                full_name=f"Reviewer {i + 1}",
                hire_date="2019-01-01T00:00:00Z",
                home_unit=home_unit,
            )
        )
    return reviewers


def assign_reviewers(application_id: str, reviewers: list) -> list:
    """Create one review assignment per reviewer. Returns assignment dicts
    in list order (lists sort by created_at ascending per PRD §2.3)."""
    for reviewer in reviewers:
        get_success_data(
            api_client.create_review_assignment(
                application_id, {"reviewer_nurse_id": reviewer["id"]}, ADMIN
            )
        )
    return get_success_data(
        api_client.list_application_assignments(application_id, ADMIN)
    )


def score_assignment(assignment_id: str, reviewer_id: str, value: int = 80) -> dict:
    return get_success_data(
        api_client.score_review_assignment(
            assignment_id, score_payload(value), make_nurse_headers(reviewer_id)
        )
    )


def get_application(application_id: str) -> dict:
    return get_success_data(api_client.get_application(application_id, ADMIN))


def decide(application_id: str, outcome: str = "APPROVE", admin_headers=None) -> dict:
    """Decide with the application's CURRENT version as the OCC token."""
    app_now = get_application(application_id)
    return get_success_data(
        api_client.decide_application(
            application_id,
            decide_payload(outcome, app_now["version"]),
            admin_headers or ADMIN,
        )
    )


def setup_submitted_application(
    employee_code: str = "RN-APP",
    home_unit: str = TEST_DEFAULTS["HOME_UNIT"],
    target_level: str = "CN_II",
    hire_date: str = "2020-01-01T00:00:00Z",
) -> dict:
    """Nurse + DRAFT application + submit. Returns dict of nurse/application."""
    nurse = create_nurse(employee_code=employee_code, hire_date=hire_date,
                         home_unit=home_unit)
    app = create_draft_application(nurse, target_level)
    app = submit_application(app, nurse["id"])
    return {"nurse": nurse, "application": app}


def setup_in_review_application(
    employee_code: str = "RN-APP",
    home_unit: str = TEST_DEFAULTS["HOME_UNIT"],
    target_level: str = "CN_II",
    hire_date: str = "2020-01-01T00:00:00Z",
    reviewer_prefix: str = "RN-REV",
) -> dict:
    """Submitted application + three PENDING review assignments (IN_REVIEW)."""
    ctx = setup_submitted_application(
        employee_code=employee_code, home_unit=home_unit,
        target_level=target_level, hire_date=hire_date,
    )
    reviewers = create_reviewers(3, home_unit, reviewer_prefix)
    assignments = assign_reviewers(ctx["application"]["id"], reviewers)
    ctx["reviewers"] = reviewers
    ctx["assignments"] = assignments
    ctx["application"] = get_application(ctx["application"]["id"])
    return ctx


def setup_scored_application(
    score: int = 80,
    employee_code: str = "RN-APP",
    home_unit: str = TEST_DEFAULTS["HOME_UNIT"],
    target_level: str = "CN_II",
    hire_date: str = "2020-01-01T00:00:00Z",
    reviewer_prefix: str = "RN-REV",
) -> dict:
    """IN_REVIEW application with all three assignments SCORED flat at `score`
    (so the committee aggregate equals `score`)."""
    ctx = setup_in_review_application(
        employee_code=employee_code, home_unit=home_unit,
        target_level=target_level, hire_date=hire_date,
        reviewer_prefix=reviewer_prefix,
    )
    for assignment, reviewer in zip(ctx["assignments"], ctx["reviewers"]):
        score_assignment(assignment["id"], reviewer["id"], score)
    ctx["application"] = get_application(ctx["application"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: full advancement (approval activates the differential)
# ---------------------------------------------------------------------------

def advance_nurse(
    nurse: dict,
    target_level: str,
    score: int = 80,
    reviewer_prefix: str = "RN-ADV",
    home_unit: str = TEST_DEFAULTS["HOME_UNIT"],
) -> dict:
    """Run the full committee flow for `nurse` to `target_level` and APPROVE.
    Returns the decided application."""
    app = create_draft_application(nurse, target_level)
    app = submit_application(app, nurse["id"])
    reviewers = create_reviewers(3, home_unit, reviewer_prefix)
    assignments = assign_reviewers(app["id"], reviewers)
    for assignment, reviewer in zip(assignments, reviewers):
        score_assignment(assignment["id"], reviewer["id"], score)
    return decide(app["id"], "APPROVE")


def advance_nurse_to_cn_iii(
    employee_code: str = "RN-CN3",
    home_unit: str = TEST_DEFAULTS["ALT_UNIT"],
    hire_date: str = "2016-01-01T00:00:00Z",
    cn_ii_differential: int = TEST_DEFAULTS["DIFFERENTIAL_CN_II_CENTS"],
    cn_iii_differential: int = TEST_DEFAULTS["DIFFERENTIAL_CN_III_CENTS"],
    cn_ii_min_score: int = 75,
    cn_iii_min_score: int = 80,
) -> dict:
    """Nurse advanced CN_I -> CN_III with ACTIVE differential.

    Publishes active CN_II and CN_III criteria, then runs two full committee
    flows. Returns {"nurse", "app2", "app3"} with the nurse re-read at the end.
    """
    create_criterion(
        target_level="CN_II", min_portfolio_score=cn_ii_min_score,
        differential_monthly_cents=cn_ii_differential,
    )
    create_criterion(
        target_level="CN_III", min_portfolio_score=cn_iii_min_score,
        differential_monthly_cents=cn_iii_differential,
    )
    nurse = create_nurse(employee_code=employee_code, hire_date=hire_date,
                         home_unit=home_unit)
    app2 = advance_nurse(nurse, "CN_II", score=80,
                         reviewer_prefix=f"{employee_code}-R2", home_unit=home_unit)
    nurse = get_nurse(nurse["id"])
    app3 = advance_nurse(nurse, "CN_III", score=85,
                         reviewer_prefix=f"{employee_code}-R3", home_unit=home_unit)
    nurse = get_nurse(nurse["id"])
    return {"nurse": nurse, "app2": app2, "app3": app3}


# ---------------------------------------------------------------------------
# Tier 4: certification / claim financial chains
# ---------------------------------------------------------------------------

def setup_nurse_with_cert_and_bonus(
    employee_code: str = "RN-CERT",
    home_unit: str = TEST_DEFAULTS["HOME_UNIT"],
    hire_date: str = "2021-01-01T00:00:00Z",
    track: str = "BASIC",
    exam_fee_cents: int = TEST_DEFAULTS["EXAM_FEE_CENTS"],
    obtained_on: str = "2026-01-01T00:00:00Z",
    expires_on: str = "2031-01-01T00:00:00Z",
    with_budget_line: bool = True,
    fiscal_year: int = 2027,
    allocated_cents: int = TEST_DEFAULTS["BUDGET_ALLOCATED_CENTS"],
) -> dict:
    """Nurse + registered certification + its accrued bonus row (+ unit budget
    line for the fiscal year). Returns nurse/cert/bonus/budget_line."""
    budget_line = None
    if with_budget_line:
        budget_line = create_budget_line(home_unit, fiscal_year, allocated_cents)
    nurse = create_nurse(employee_code=employee_code, hire_date=hire_date,
                         home_unit=home_unit)
    cert = create_certification(
        nurse["id"], track=track, exam_fee_cents=exam_fee_cents,
        obtained_on=obtained_on, expires_on=expires_on,
    )
    bonus = get_accrued_bonus(cert["id"])
    return {
        "nurse": nurse,
        "certification": cert,
        "bonus": bonus,
        "budget_line": budget_line,
    }


def setup_approved_claim(
    claimed_amount_cents: int = 30000,
    employee_code: str = "RN-CLAIM",
    home_unit: str = TEST_DEFAULTS["HOME_UNIT"],
    track: str = "BASIC",
    exam_fee_cents: int = TEST_DEFAULTS["EXAM_FEE_CENTS"],
    allocated_cents: int = TEST_DEFAULTS["BUDGET_ALLOCATED_CENTS"],
) -> dict:
    """Nurse + cert + claim, approved. Returns the fixture dict with claim."""
    ctx = setup_nurse_with_cert_and_bonus(
        employee_code=employee_code, home_unit=home_unit, track=track,
        exam_fee_cents=exam_fee_cents, allocated_cents=allocated_cents,
    )
    claim = create_claim(ctx["certification"]["id"], ctx["nurse"]["id"],
                         claimed_amount_cents)
    claim = approve_claim(claim["id"])
    ctx["claim"] = claim
    return ctx
