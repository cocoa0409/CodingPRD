"""Composite setup helpers for the Special Education IEP benchmark.

Each fixture builds its preconditions from scratch through PRD-declared endpoints
(see PRD §3.x). The runner restarts the API server before every individual pytest
test, so each fixture starts from an empty database — no entities, no clock state.

Fixtures use `get_success_data()` (lenient validator) so setup failures surface
as clear "Setup failed" traces rather than cryptic assertion failures.

Identity model: all four roles are opaque (PRD §2.1). The only place X-User-ID
matters beyond authentication is segregation of duties (PRD §2.1) — the requesting
CaseManager vs the finalizing Evaluator, and the convening CaseManager vs the
activating SpecialEdAdmin. The fixtures use the standard distinct ids
(cm_1 for the case manager, ev_1 for the evaluator, adm_1 for the admin,
par_1 for the parent) so the happy-path flows never trip the SoD guard. Tests that
exercise SoD pass explicit headers to override these.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    set_clock_payload,
    create_student_payload,
    create_evaluation_payload,
    decide_consent_payload,
    create_iep_payload,
    open_amendment_payload,
    create_goal_payload,
    create_progress_report_payload,
    create_related_service_payload,
    discontinue_related_service_payload,
    create_transition_plan_payload,
)
from .test_users import (
    make_admin_headers,
    make_case_manager_headers,
    make_evaluator_headers,
    make_parent_headers,
)


_ADMIN = make_admin_headers("adm_1")
_CM = make_case_manager_headers("cm_1")
_EV = make_evaluator_headers("ev_1")
_PAR = make_parent_headers("par_1")

DEFAULT_CLOCK = "2026-03-01T09:00:00Z"


# ─── Tier 0: clock + raw creates ────────────────────────────────
def set_clock(iso8601: str = DEFAULT_CLOCK) -> dict:
    """Pin the logical server clock (PRD §3.10)."""
    return get_success_data(api_client.set_clock(set_clock_payload(iso8601), _ADMIN))


def create_student(clock: str = DEFAULT_CLOCK, set_clock_first: bool = True, **overrides) -> dict:
    """Register a student (PRD §3.1). Returns the Student in NOT_EVALUATED."""
    if set_clock_first:
        set_clock(clock)
    return get_success_data(
        api_client.create_student(create_student_payload(**overrides), _ADMIN)
    )


def get_student(student_id: str) -> dict:
    return get_success_data(api_client.get_student(student_id, _CM))


def get_iep(iep_id: str) -> dict:
    return get_success_data(api_client.get_iep(iep_id, _CM))


def iep_version(iep_id: str) -> int:
    return get_iep(iep_id)["version"]


def get_goal(goal_id: str) -> dict:
    return get_success_data(api_client.get_goal(goal_id, _CM))


# ─── Tier 1: eligibility ────────────────────────────────────────
def _grant_evaluation_consent(student_id: str) -> str:
    """Find the PENDING EVALUATION consent for the student and GRANT it.

    Returns the consent request id."""
    data, _meta = _list_consent(
        student_id=student_id, consent_type="EVALUATION", status="PENDING"
    )
    cr_id = data[0]["id"]
    get_success_data(
        api_client.decide_consent(cr_id, decide_consent_payload("GRANT"), _PAR)
    )
    return cr_id


def _list_consent(**params):
    resp = api_client.list_consent_requests(_PAR, params=params)
    body = resp.json()
    return body["data"], body.get("meta", {})


def make_eligible_student(
    clock: str = DEFAULT_CLOCK,
    eval_overrides: dict = None,
    student_overrides: dict = None,
) -> dict:
    """Register a student and drive an INITIAL evaluation to FINALIZED with an
    ELIGIBLE outcome, leaving the student ELIGIBLE (PRD §3.2, §3.3).

    Default scores 110/70/75 INITIAL → composite 33.50 → ELIGIBLE.
    Returns the Student dict (re-fetched, so eligibility_status is current)."""
    student = create_student(clock=clock, **(student_overrides or {}))
    eval_id = make_finalized_evaluation(
        student["id"], eval_overrides=eval_overrides, set_clock_first=False
    )["id"]
    return get_student(student["id"])


def make_finalized_evaluation(
    student_id: str,
    eval_overrides: dict = None,
    set_clock_first: bool = False,
    clock: str = DEFAULT_CLOCK,
) -> dict:
    """Open an evaluation on an existing student and drive it to FINALIZED
    (request-consent → grant → begin → finalize). Returns the finalized
    Evaluation (PRD §3.2)."""
    if set_clock_first:
        set_clock(clock)
    ev = get_success_data(
        api_client.create_evaluation(
            create_evaluation_payload(student_id, **(eval_overrides or {})), _CM
        )
    )
    eval_id = ev["id"]
    get_success_data(api_client.request_consent(eval_id, _CM))
    _grant_evaluation_consent(student_id)
    get_success_data(api_client.begin_evaluation(eval_id, _EV))
    return get_success_data(api_client.finalize_evaluation(eval_id, _EV))


def make_evaluation_in_progress(student_id: str, eval_overrides: dict = None) -> dict:
    """Open an evaluation and drive it to IN_PROGRESS (consent granted, begun),
    stopping short of finalize. Returns the IN_PROGRESS Evaluation (PRD §3.2)."""
    ev = get_success_data(
        api_client.create_evaluation(
            create_evaluation_payload(student_id, **(eval_overrides or {})), _CM
        )
    )
    eval_id = ev["id"]
    get_success_data(api_client.request_consent(eval_id, _CM))
    _grant_evaluation_consent(student_id)
    return get_success_data(api_client.begin_evaluation(eval_id, _EV))


# ─── Tier 2: IEP lifecycle ──────────────────────────────────────
def create_draft_iep(student_id: str, **overrides) -> dict:
    """Draft an IEP for a student (PRD §3.5). Returns the DRAFT IEP."""
    return get_success_data(
        api_client.create_iep(create_iep_payload(student_id, **overrides), _CM)
    )


def make_draft_iep_for_eligible_student(
    clock: str = DEFAULT_CLOCK,
    iep_overrides: dict = None,
    student_overrides: dict = None,
    eval_overrides: dict = None,
):
    """Eligible student + a fresh DRAFT IEP. Returns (student, iep)."""
    student = make_eligible_student(
        clock=clock, eval_overrides=eval_overrides, student_overrides=student_overrides
    )
    iep = create_draft_iep(student["id"], **(iep_overrides or {}))
    return student, iep


def grant_placement_consent(student_id: str, iep_id: str) -> str:
    """Find the PENDING PLACEMENT consent for this IEP and GRANT it.

    Returns the placement consent request id (PRD §3.4, §3.5)."""
    data, _meta = _list_consent(
        student_id=student_id, iep_id=iep_id, consent_type="PLACEMENT", status="PENDING"
    )
    cr_id = data[0]["id"]
    get_success_data(
        api_client.decide_consent(cr_id, decide_consent_payload("GRANT"), _PAR)
    )
    return cr_id


def make_meeting_held_iep(
    clock: str = DEFAULT_CLOCK,
    iep_overrides: dict = None,
    student_overrides: dict = None,
):
    """Eligible student + IEP in MEETING_HELD with its PLACEMENT consent still
    PENDING. Returns (student, iep, placement_cr_id) (PRD §3.5)."""
    student, iep = make_draft_iep_for_eligible_student(
        clock=clock, iep_overrides=iep_overrides, student_overrides=student_overrides
    )
    get_success_data(api_client.hold_meeting(iep["id"], _CM))
    data, _meta = _list_consent(
        student_id=student["id"], iep_id=iep["id"],
        consent_type="PLACEMENT", status="PENDING",
    )
    return student, get_iep(iep["id"]), data[0]["id"]


def make_active_iep(
    clock: str = DEFAULT_CLOCK,
    iep_overrides: dict = None,
    student_overrides: dict = None,
):
    """Eligible student + IEP driven to ACTIVE (meeting held, placement consent
    granted, activated). Returns (student, iep, placement_cr_id) where iep is
    the re-fetched ACTIVE IEP (PRD §3.5)."""
    student, iep, plc_cr_id = make_meeting_held_iep(
        clock=clock, iep_overrides=iep_overrides, student_overrides=student_overrides
    )
    grant_placement_consent(student["id"], iep["id"])
    get_success_data(api_client.activate_iep(iep["id"], _ADMIN))
    return get_student(student["id"]), get_iep(iep["id"]), plc_cr_id


# ─── Tier 3: goals & progress ───────────────────────────────────
def create_goal(iep_id: str, **overrides) -> dict:
    """Add a goal to an IEP (PRD §3.6). Returns the ACTIVE Goal."""
    return get_success_data(
        api_client.create_goal(create_goal_payload(iep_id, **overrides), _CM)
    )


def make_goal_on_eligible_student(
    clock: str = DEFAULT_CLOCK,
    iep_overrides: dict = None,
    goal_overrides: dict = None,
    student_overrides: dict = None,
):
    """Eligible student + DRAFT IEP + one Goal. Returns (student, iep, goal)."""
    student, iep = make_draft_iep_for_eligible_student(
        clock=clock, iep_overrides=iep_overrides, student_overrides=student_overrides
    )
    goal = create_goal(iep["id"], **(goal_overrides or {}))
    return student, iep, goal


def record_progress_report(goal_id: str, reporting_period: int, measured_value) -> dict:
    """Record one progress data point (PRD §3.6). Returns the ProgressReport."""
    return get_success_data(
        api_client.create_progress_report(
            create_progress_report_payload(
                goal_id, reporting_period=reporting_period, measured_value=measured_value
            ),
            _CM,
        )
    )


def setup_goal_with_reports(
    reports,
    clock: str = DEFAULT_CLOCK,
    iep_overrides: dict = None,
    goal_overrides: dict = None,
):
    """Eligible student + DRAFT IEP + Goal, then record the given progress
    reports. `reports` is a list of (reporting_period, measured_value) tuples.

    Returns (student, iep, goal_id) (PRD §3.6, §3.7)."""
    student, iep, goal = make_goal_on_eligible_student(
        clock=clock, iep_overrides=iep_overrides, goal_overrides=goal_overrides
    )
    for period, value in reports:
        record_progress_report(goal["id"], period, value)
    return student, iep, goal["id"]


# ─── Tier 4: related services & LRE ─────────────────────────────
def add_related_service(iep_id: str, expected_iep_version: int, **overrides) -> dict:
    """Add an OT/PT/Speech related service (PRD §3.8). Returns the ACTIVE service."""
    return get_success_data(
        api_client.create_related_service(
            create_related_service_payload(iep_id, expected_iep_version, **overrides), _CM
        )
    )


def make_draft_iep_with_service(
    service_overrides: dict = None,
    clock: str = DEFAULT_CLOCK,
    iep_overrides: dict = None,
):
    """Eligible student + DRAFT IEP + one related service added at the current
    IEP version. Returns (student, iep_after, service) where iep_after is the
    re-fetched IEP (LRE recomputed) (PRD §3.8)."""
    student, iep = make_draft_iep_for_eligible_student(
        clock=clock, iep_overrides=iep_overrides
    )
    service = add_related_service(
        iep["id"], iep["version"], **(service_overrides or {})
    )
    return student, get_iep(iep["id"]), service


def discontinue_service(rs_id: str, expected_iep_version: int) -> dict:
    """Discontinue a related service (PRD §3.8). Returns the service response."""
    return get_success_data(
        api_client.discontinue_related_service(
            rs_id, discontinue_related_service_payload(expected_iep_version), _CM
        )
    )


# ─── Tier 5: transition plans ───────────────────────────────────
def create_transition_plan(iep_id: str, **overrides) -> dict:
    """Create a transition plan on an IEP (PRD §3.9). Returns the DRAFT plan."""
    return get_success_data(
        api_client.create_transition_plan(
            create_transition_plan_payload(iep_id, **overrides), _CM
        )
    )
