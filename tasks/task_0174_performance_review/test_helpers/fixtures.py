"""Composite setup helpers for multi-step test prerequisites.

The Performance Review & Compensation Planning API has long preconditions
for most testable claims:

* Submitting a ReviewCase requires the case to have its full goal set
  (weights summing to 100), every goal scored, manager_rating set, and
  >= 2 SUBMITTED FeedbackRequests on file (PRD §3.3).
* Driving a ReviewCase to FINALIZED requires a CalibrationSession to
  commit covering it with a bell-curve-compliant proposed_ratings list
  (PRD §3.5).
* Creating a CompPlan requires a FINALIZED ReviewCase and the Cycle to
  be in COMP_PLANNING (PRD §3.7).

These helpers encapsulate those sequences so tests focus on assertions.

Identity threading is mandatory (PRD §2.1): roles HRBP, Manager,
Reviewer, Approver are entity_backed:Employee, so any ownership-gated
call here MUST be made via `make_<role>_headers(employee_id)` with the
acting Employee.id. The shared placeholders in TEST_USERS are reserved
for auth / 404 probes only.

All setup uses `get_success_data()` (lenient validator) so a setup
failure surfaces as a clear "Setup step failed" assertion rather than a
confusing downstream assertion mismatch.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CADENCE_MULTIPLIER,
    PIP_DURATION_DAYS,
    PROMO_BUMP_FACTOR,
    PROMO_BUMP_PCT,
    TEST_DEFAULTS,
    ANNUAL_MERIT_PCT,
    equity_base_units,
    semi_annual_merit_pct,
)
from .factories import (
    advance_clock_payload,
    create_calibration_session_payload,
    create_comp_plan_payload,
    create_cycle_payload,
    create_employee_payload,
    create_feedback_request_payload,
    create_goal_payload,
    create_review_case_payload,
    proposals_payload,
    submit_feedback_request_payload,
)
from .test_users import (
    TEST_USERS,
    make_approver_headers,
    make_hrbp_headers,
    make_manager_headers,
    make_reviewer_headers,
)


# ===========================================================================
# Data carriers — light bundles returned by composite fixtures so tests can
# pluck the bits they need without juggling tuples of half a dozen entities.
# ===========================================================================
@dataclass
class EmployeeBundle:
    employee: Dict[str, Any]
    headers: Dict[str, str]

    @property
    def id(self) -> str:
        return self.employee["id"]


@dataclass
class ReviewCaseBundle:
    cycle: Dict[str, Any]
    review_case: Dict[str, Any]
    subject: Dict[str, Any]
    manager: EmployeeBundle
    hrbp: EmployeeBundle
    reviewers: List[EmployeeBundle] = field(default_factory=list)
    goals: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class CycleBundle:
    cycle: Dict[str, Any]
    admin_headers: Dict[str, str] = field(
        default_factory=lambda: TEST_USERS["admin_headers"],
    )


# ===========================================================================
# Tier 1 — Employee creation (entity_backed identity threading)
# ===========================================================================
def create_employee_with_role(role: str,
                              department: str = "Eng",
                              job_level: int = 4,
                              base_salary_cents: int = 10_000_000,
                              manager_employee_id: Optional[str] = None,
                              equity_units_outstanding: int = 0,
                              **overrides: Any) -> EmployeeBundle:
    """Create an Employee and return it bundled with headers minted under
    the requested role.

    For the four entity_backed roles (HRBP, Manager, Reviewer, Approver),
    the headers' X-User-ID equals the new Employee.id — PRD §2.1.
    """
    payload = create_employee_payload(
        department=department,
        job_level=job_level,
        base_salary_cents=base_salary_cents,
        equity_units_outstanding=equity_units_outstanding,
        **overrides,
    )
    if manager_employee_id is not None:
        payload["manager_employee_id"] = manager_employee_id
    res = api_client.create_employee(payload, TEST_USERS["admin_headers"])
    emp = get_success_data(res)

    if role == "HRBP":
        headers = make_hrbp_headers(emp["id"])
    elif role == "Manager":
        headers = make_manager_headers(emp["id"])
    elif role == "Reviewer":
        headers = make_reviewer_headers(emp["id"])
    elif role == "Approver":
        headers = make_approver_headers(emp["id"])
    elif role == "Admin":
        # Admin is opaque; X-User-ID is not tied to an entity, so the
        # default shared admin headers are appropriate. We still return a
        # bundle so callers can use the .employee snapshot.
        headers = TEST_USERS["admin_headers"]
    else:
        raise ValueError(f"Unknown role: {role}")
    return EmployeeBundle(employee=emp, headers=headers)


def create_active_employee(department: str = "Eng",
                           job_level: int = 4,
                           base_salary_cents: int = 10_000_000,
                           manager_employee_id: Optional[str] = None,
                           **overrides: Any) -> Dict[str, Any]:
    """Plain ACTIVE Employee with no acting-role binding. For subjects
    of reviews / comp plans, not for callers."""
    payload = create_employee_payload(
        department=department,
        job_level=job_level,
        base_salary_cents=base_salary_cents,
        **overrides,
    )
    if manager_employee_id is not None:
        payload["manager_employee_id"] = manager_employee_id
    res = api_client.create_employee(payload, TEST_USERS["admin_headers"])
    return get_success_data(res)


# ===========================================================================
# Tier 1b — Cycle creation
# ===========================================================================
def create_open_cycle(cadence: str = "ANNUAL",
                      merit_budget_cents: Optional[int] = None,
                      equity_refresh_pool_units: Optional[int] = None,
                      bell_curve_target: Optional[Dict[str, int]] = None,
                      review_window_start: Optional[str] = None,
                      review_window_end: Optional[str] = None,
                      **overrides: Any) -> Dict[str, Any]:
    """POST /cycles. Returns the new OPEN Cycle."""
    payload = create_cycle_payload(cadence=cadence)
    if merit_budget_cents is not None:
        payload["merit_budget_cents"] = merit_budget_cents
    if equity_refresh_pool_units is not None:
        payload["equity_refresh_pool_units"] = equity_refresh_pool_units
    if bell_curve_target is not None:
        payload["bell_curve_target"] = dict(bell_curve_target)
    if review_window_start is not None:
        payload["review_window_start"] = review_window_start
    if review_window_end is not None:
        payload["review_window_end"] = review_window_end
    payload.update(overrides)
    res = api_client.create_cycle(payload, TEST_USERS["admin_headers"])
    return get_success_data(res)


# ===========================================================================
# Tier 2 — ReviewCase scaffolding (DRAFT with all submit preconditions)
# ===========================================================================
def add_goals_summing_to_100(cycle_id: str,
                             review_case_id: str,
                             manager_headers: Dict[str, str],
                             weights: Tuple[int, ...] = (60, 40),
                             self_scores: Optional[Tuple[int, ...]] = None,
                             manager_scores: Optional[Tuple[int, ...]] = None,
                             ) -> List[Dict[str, Any]]:
    """Add goals whose weights sum to 100. PRD §3.3: 'the sum of `weight`
    across the case's goals equals 100' is a submit precondition."""
    assert sum(weights) == 100, (
        f"Test helper bug: weights must sum to 100; got {weights}"
    )
    self_scores = self_scores or tuple(3 for _ in weights)
    manager_scores = manager_scores or tuple(4 for _ in weights)
    goals: List[Dict[str, Any]] = []
    for w, ss, ms in zip(weights, self_scores, manager_scores):
        body = create_goal_payload(weight=w,
                                   self_score=ss,
                                   manager_score=ms)
        res = api_client.create_goal(cycle_id, review_case_id, body,
                                     manager_headers)
        goals.append(get_success_data(res))
    return goals


def attach_two_submitted_feedback_requests(
        cycle: Dict[str, Any],
        review_case: Dict[str, Any],
        subject: Dict[str, Any],
        hrbp: EmployeeBundle,
) -> List[EmployeeBundle]:
    """Create two distinct reviewer Employees, open a FeedbackRequest for
    each on the case, and SUBMIT each one. Returns the reviewer bundles.

    PRD §3.3: the submit precondition `peer_feedback_count >= 2` is met
    by having at least two `SUBMITTED` feedback requests on the case.
    The reviewers are distinct from the subject (PRD §3.4 self-feedback
    forbidden) and from each other.
    """
    reviewers: List[EmployeeBundle] = []
    for i in range(2):
        rb = create_employee_with_role(
            "Reviewer",
            department=subject["department"],
        )
        fb_res = api_client.create_feedback_request(
            cycle["id"], review_case["id"],
            create_feedback_request_payload(rb.id, relation="PEER"),
            hrbp.headers,
        )
        fb = get_success_data(fb_res)
        sub_res = api_client.submit_feedback_request(
            cycle["id"], review_case["id"], fb["id"],
            submit_feedback_request_payload(),
            rb.headers,
        )
        get_success_data(sub_res)
        reviewers.append(rb)
    return reviewers


def setup_submittable_review_case(
        cycle: Optional[Dict[str, Any]] = None,
        cadence: str = "ANNUAL",
        subject_department: str = "Eng",
        subject_job_level: int = 4,
        subject_base_salary_cents: int = 10_000_000,
        manager_rating: str = "EXCEEDS",
        weights: Tuple[int, ...] = (60, 40),
        self_scores: Tuple[int, ...] = (3, 3),
        manager_scores: Tuple[int, ...] = (4, 4),
        attach_feedback: bool = True,
) -> ReviewCaseBundle:
    """Create the full DRAFT-with-everything-but-submit scaffold:

    1. (Optional) Create OPEN Cycle.
    2. Create Manager Employee.
    3. Create HRBP Employee.
    4. Create subject Employee whose manager_employee_id == manager.id.
    5. Open ReviewCase for subject (acting as HRBP).
    6. Add goals with weights summing to 100, each scored.
    7. Set manager_rating via PATCH on the case (acting as Manager).
    8. (Optional) Attach two SUBMITTED FeedbackRequests.

    The returned bundle exposes every actor and entity used.
    """
    cyc = cycle or create_open_cycle(cadence=cadence)
    # Manager and HRBP are independent acting Employees.
    mgr = create_employee_with_role("Manager",
                                    department=subject_department)
    hrbp = create_employee_with_role("HRBP",
                                     department=subject_department)
    subj = create_active_employee(
        department=subject_department,
        job_level=subject_job_level,
        base_salary_cents=subject_base_salary_cents,
        manager_employee_id=mgr.id,
    )
    # PRD §3.3: HRBP or Manager opens the case. We open as HRBP so that
    # the Manager id is snapshotted from the subject's manager record.
    rc_res = api_client.create_review_case(
        cyc["id"],
        create_review_case_payload(subj["id"]),
        hrbp.headers,
    )
    rc = get_success_data(rc_res)
    goals = add_goals_summing_to_100(
        cyc["id"], rc["id"], mgr.headers,
        weights=weights,
        self_scores=self_scores,
        manager_scores=manager_scores,
    )
    # Set manager_rating (PRD §3.3 lists manager_rating as the only
    # mutable ReviewCase field via PATCH).
    pat_res = api_client.update_review_case(
        cyc["id"], rc["id"],
        {"manager_rating": manager_rating},
        mgr.headers,
    )
    rc = get_success_data(pat_res)
    reviewers: List[EmployeeBundle] = []
    if attach_feedback:
        reviewers = attach_two_submitted_feedback_requests(
            cyc, rc, subj, hrbp,
        )
    # Re-read case so peer_feedback_count is up to date.
    rc = get_success_data(api_client.get_review_case(
        cyc["id"], rc["id"], hrbp.headers,
    ))
    return ReviewCaseBundle(
        cycle=cyc, review_case=rc, subject=subj,
        manager=mgr, hrbp=hrbp, reviewers=reviewers, goals=goals,
    )


def submit_review_case(bundle: ReviewCaseBundle) -> ReviewCaseBundle:
    """POST .../submit using the Manager. Updates bundle.review_case."""
    res = api_client.submit_review_case(
        bundle.cycle["id"], bundle.review_case["id"], bundle.manager.headers,
    )
    bundle.review_case = get_success_data(res)
    return bundle


# ===========================================================================
# Tier 3 — Calibration-driven FINALIZATION pipeline
# ===========================================================================
def _bell_curve_for_single_rating(rating: str) -> Dict[str, int]:
    """A bell-curve target that allows a single proposed rating to pass
    the 5-pp tolerance: 100 in the target bucket, 0 elsewhere.

    PRD §3.5: compliance is per-bucket abs(observed_pct - target_pct)
    <= 5. With one proposal of rating R: observed_pct[R] = 100 (target
    must be in [95..100]); every other bucket observed_pct = 0 (target
    must be in [0..5]). Five integer percents summing to 100: the only
    valid shape is {R: 100, others: 0}. Two singletons of the same
    rating reach the same conclusion.
    """
    return {r: (100 if r == rating else 0) for r in
            ("OUTSTANDING", "EXCEEDS", "MEETS",
             "NEEDS_IMPROVEMENT", "UNSATISFACTORY")}


def finalize_review_case_via_calibration(
        bundle: ReviewCaseBundle,
        final_rating: str,
) -> ReviewCaseBundle:
    """Push a SUBMITTED ReviewCase through to FINALIZED by:

    1. Lock the Cycle (OPEN -> IN_CALIBRATION); ReviewCase LOCKED.
    2. Create a CalibrationSession for the subject's department, with a
       distinct HRBP facilitator (PRD §2.11 segregation prevents using
       the same HRBP if that HRBP is also a manager of any covered case;
       we use the bundle.hrbp who is NOT a manager of the case to keep
       it safe, but allow override via a new HRBP).
    3. PATCH proposals = [{review_case_id: rc.id, proposed_rating: final}].
    4. Start the session.
    5. Commit the session.

    After commit, Cycle.status = COMP_PLANNING (PRD §3.5 last-department
    commit), ReviewCase.status = FINALIZED, final_rating is set, and if
    final_rating is NEEDS_IMPROVEMENT or UNSATISFACTORY an ACTIVE PIPCase
    is auto-created for the subject (PRD §3.5).
    """
    # The bundle's HRBP did not manage the case (only the Manager
    # bundle.manager did), so it satisfies facilitator non-conflict.
    facilitator = bundle.hrbp

    # 1. Submit if not yet submitted.
    if bundle.review_case["status"] == "DRAFT":
        submit_review_case(bundle)
    assert bundle.review_case["status"] == "SUBMITTED", (
        f"Setup: review case must be SUBMITTED before lock-reviews; "
        f"got {bundle.review_case['status']}"
    )

    # Adjust bell curve target so the single-proposed-rating passes.
    target = _bell_curve_for_single_rating(final_rating)
    get_success_data(api_client.update_cycle(
        bundle.cycle["id"],
        {"bell_curve_target": target},
        TEST_USERS["admin_headers"],
    ))

    # 2. Lock the cycle (OPEN -> IN_CALIBRATION). Acting HRBP.
    lock_res = api_client.lock_reviews(
        bundle.cycle["id"], facilitator.headers,
    )
    bundle.cycle = get_success_data(lock_res)
    # 3. Create CalibrationSession in the subject's department.
    cs_res = api_client.create_calibration_session(
        bundle.cycle["id"],
        create_calibration_session_payload(
            department=bundle.subject["department"],
            facilitator_employee_id=facilitator.id,
        ),
        facilitator.headers,
    )
    cs = get_success_data(cs_res)
    # 4. Set proposals to cover the single case.
    pr_res = api_client.update_calibration_proposals(
        bundle.cycle["id"], cs["id"],
        proposals_payload([
            {"review_case_id": bundle.review_case["id"],
             "proposed_rating": final_rating},
        ]),
        facilitator.headers,
    )
    cs = get_success_data(pr_res)
    # 5. Start.
    start_res = api_client.start_calibration_session(
        bundle.cycle["id"], cs["id"], facilitator.headers,
    )
    get_success_data(start_res)
    # 6. Commit.
    commit_res = api_client.commit_calibration_session(
        bundle.cycle["id"], cs["id"], facilitator.headers,
    )
    get_success_data(commit_res)
    # Re-read state. GET /review-cases/{id} is HRBP/Manager/Approver/Reviewer
    # only (PRD §4) — Admin is NOT authorised, so we re-read as the HRBP
    # facilitator. GET /cycles/{id} does include Admin, but we use HRBP
    # for symmetry.
    bundle.cycle = get_success_data(api_client.get_cycle(
        bundle.cycle["id"], facilitator.headers,
    ))
    bundle.review_case = get_success_data(api_client.get_review_case(
        bundle.cycle["id"], bundle.review_case["id"],
        facilitator.headers,
    ))
    return bundle


def setup_finalized_review_case(
        cadence: str = "ANNUAL",
        final_rating: str = "EXCEEDS",
        subject_department: str = "Eng",
        subject_job_level: int = 4,
        subject_base_salary_cents: int = 10_000_000,
        cycle: Optional[Dict[str, Any]] = None,
        merit_budget_cents: Optional[int] = None,
        equity_refresh_pool_units: Optional[int] = None,
) -> ReviewCaseBundle:
    """Shortcut: build a fully FINALIZED ReviewCase with the requested
    final_rating. After this returns, Cycle.status == COMP_PLANNING and
    the subject is ready for a CompPlan.

    The bell_curve_target is rewritten by
    finalize_review_case_via_calibration() so callers don't need to pre-
    align it. The cycle's merit_budget_cents / equity_refresh_pool_units
    default to the generous TEST_DEFAULTS values; pass them explicitly to
    exercise fiscal gates.
    """
    cyc = cycle or create_open_cycle(
        cadence=cadence,
        merit_budget_cents=merit_budget_cents,
        equity_refresh_pool_units=equity_refresh_pool_units,
    )
    # Set bell curve to all-MEETS by default, the helper rewrites later.
    bundle = setup_submittable_review_case(
        cycle=cyc,
        cadence=cadence,
        subject_department=subject_department,
        subject_job_level=subject_job_level,
        subject_base_salary_cents=subject_base_salary_cents,
        manager_rating=final_rating,
    )
    bundle = finalize_review_case_via_calibration(bundle, final_rating)
    return bundle


# ===========================================================================
# Tier 4 — Multi-case calibration (covers full department with two+ cases)
# ===========================================================================
@dataclass
class DepartmentCalibrationBundle:
    cycle: Dict[str, Any]
    department: str
    hrbp: EmployeeBundle
    facilitator: EmployeeBundle
    review_cases: List[Dict[str, Any]]
    subjects: List[Dict[str, Any]]
    managers: List[EmployeeBundle]
    calibration_session: Optional[Dict[str, Any]] = None


def setup_department_with_locked_cases(
        ratings: Tuple[str, ...],
        cadence: str = "ANNUAL",
        department: str = "Eng",
        subject_job_level: int = 4,
        subject_base_salary_cents: int = 10_000_000,
        bell_curve_target: Optional[Dict[str, int]] = None,
        merit_budget_cents: Optional[int] = None,
) -> DepartmentCalibrationBundle:
    """Create a cycle and N submittable review cases in the named
    department; each case has its own Manager. After lock-reviews, every
    case is LOCKED and the cycle is IN_CALIBRATION.

    `ratings` declares the manager_rating to set on each case (and is the
    natural seed for the eventual proposed_rating choice). Length of
    ratings is the number of cases / subjects created.

    No CalibrationSession is created here — call
    `attach_calibration_session()` once the right facilitator
    bell-curve-target choice is known.
    """
    cyc = create_open_cycle(
        cadence=cadence,
        merit_budget_cents=merit_budget_cents,
        bell_curve_target=bell_curve_target,
    )
    hrbp = create_employee_with_role("HRBP", department=department)
    facilitator = hrbp  # default: same HRBP runs lock and (later) calibration.

    managers: List[EmployeeBundle] = []
    subjects: List[Dict[str, Any]] = []
    review_cases: List[Dict[str, Any]] = []
    for rating in ratings:
        mgr = create_employee_with_role("Manager", department=department)
        subj = create_active_employee(
            department=department,
            job_level=subject_job_level,
            base_salary_cents=subject_base_salary_cents,
            manager_employee_id=mgr.id,
        )
        managers.append(mgr)
        subjects.append(subj)
        rc = get_success_data(api_client.create_review_case(
            cyc["id"],
            create_review_case_payload(subj["id"]),
            hrbp.headers,
        ))
        add_goals_summing_to_100(cyc["id"], rc["id"], mgr.headers)
        rc = get_success_data(api_client.update_review_case(
            cyc["id"], rc["id"],
            {"manager_rating": rating},
            mgr.headers,
        ))
        # Attach two SUBMITTED feedback requests to satisfy submit gate.
        for _ in range(2):
            rev = create_employee_with_role("Reviewer", department=department)
            fr = get_success_data(api_client.create_feedback_request(
                cyc["id"], rc["id"],
                create_feedback_request_payload(rev.id, relation="PEER"),
                hrbp.headers,
            ))
            get_success_data(api_client.submit_feedback_request(
                cyc["id"], rc["id"], fr["id"],
                submit_feedback_request_payload(),
                rev.headers,
            ))
        # Submit
        rc = get_success_data(api_client.submit_review_case(
            cyc["id"], rc["id"], mgr.headers,
        ))
        review_cases.append(rc)

    # Lock the cycle: every case moves SUBMITTED -> LOCKED, cycle -> IN_CALIBRATION.
    cyc = get_success_data(api_client.lock_reviews(
        cyc["id"], facilitator.headers,
    ))
    # Re-read every case so callers see status = LOCKED.
    review_cases = [
        get_success_data(api_client.get_review_case(
            cyc["id"], rc["id"], hrbp.headers,
        )) for rc in review_cases
    ]
    return DepartmentCalibrationBundle(
        cycle=cyc, department=department, hrbp=hrbp,
        facilitator=facilitator, review_cases=review_cases,
        subjects=subjects, managers=managers,
    )


def attach_calibration_session(
        dept_bundle: DepartmentCalibrationBundle,
        proposed_ratings: List[str],
        facilitator: Optional[EmployeeBundle] = None,
) -> DepartmentCalibrationBundle:
    """Create a CalibrationSession, push proposals, start the session.

    `proposed_ratings[i]` becomes the proposed_rating for
    review_cases[i]. Caller is responsible for ensuring the resulting
    distribution complies with the cycle's bell_curve_target (PRD §3.5)
    or for handling the expected ERR_BELL_CURVE_VIOLATED outcome at
    commit.
    """
    assert len(proposed_ratings) == len(dept_bundle.review_cases), (
        f"proposed_ratings count {len(proposed_ratings)} must match "
        f"locked review case count {len(dept_bundle.review_cases)}"
    )
    fac = facilitator or dept_bundle.facilitator
    cs = get_success_data(api_client.create_calibration_session(
        dept_bundle.cycle["id"],
        create_calibration_session_payload(
            department=dept_bundle.department,
            facilitator_employee_id=fac.id,
        ),
        fac.headers,
    ))
    pairs = [
        {"review_case_id": rc["id"], "proposed_rating": rating}
        for rc, rating in zip(dept_bundle.review_cases, proposed_ratings)
    ]
    cs = get_success_data(api_client.update_calibration_proposals(
        dept_bundle.cycle["id"], cs["id"],
        proposals_payload(pairs),
        fac.headers,
    ))
    cs = get_success_data(api_client.start_calibration_session(
        dept_bundle.cycle["id"], cs["id"], fac.headers,
    ))
    dept_bundle.calibration_session = cs
    return dept_bundle


# ===========================================================================
# Tier 5 — Comp planning shortcuts
# ===========================================================================
@dataclass
class CompPlanBundle:
    cycle: Dict[str, Any]
    review_case: Dict[str, Any]
    subject: Dict[str, Any]
    manager: EmployeeBundle
    hrbp: EmployeeBundle
    approver: EmployeeBundle
    comp_plan: Dict[str, Any]


def create_approver_for(bundle: ReviewCaseBundle,
                        department: Optional[str] = None) -> EmployeeBundle:
    """Mint a new Approver Employee distinct from the case's Manager.

    PRD §2.11: the approver's X-User-ID must not equal the pinned
    ReviewCase.manager_employee_id. Using a freshly-created Employee
    guarantees that.
    """
    return create_employee_with_role(
        "Approver",
        department=department or bundle.subject["department"],
    )


def setup_draft_comp_plan(
        cadence: str = "ANNUAL",
        final_rating: str = "EXCEEDS",
        subject_department: str = "Eng",
        subject_job_level: int = 4,
        subject_base_salary_cents: int = 10_000_000,
        promotion_to_level: Optional[int] = None,
        merit_budget_cents: Optional[int] = None,
        equity_refresh_pool_units: Optional[int] = None,
) -> CompPlanBundle:
    """One-call helper: build a FINALIZED ReviewCase, then create a DRAFT
    CompPlan against it. Returns everything needed to drive the plan
    through propose/approve/reject/recall."""
    rc_bundle = setup_finalized_review_case(
        cadence=cadence,
        final_rating=final_rating,
        subject_department=subject_department,
        subject_job_level=subject_job_level,
        subject_base_salary_cents=subject_base_salary_cents,
        merit_budget_cents=merit_budget_cents,
        equity_refresh_pool_units=equity_refresh_pool_units,
    )
    approver = create_approver_for(rc_bundle)
    plan = get_success_data(api_client.create_comp_plan(
        rc_bundle.cycle["id"],
        create_comp_plan_payload(
            rc_bundle.subject["id"],
            promotion_to_level=promotion_to_level,
        ),
        rc_bundle.manager.headers,
    ))
    return CompPlanBundle(
        cycle=rc_bundle.cycle,
        review_case=rc_bundle.review_case,
        subject=rc_bundle.subject,
        manager=rc_bundle.manager,
        hrbp=rc_bundle.hrbp,
        approver=approver,
        comp_plan=plan,
    )


def propose_plan(bundle: CompPlanBundle) -> CompPlanBundle:
    """POST .../propose using the Manager."""
    res = api_client.propose_comp_plan(
        bundle.cycle["id"], bundle.comp_plan["id"], bundle.manager.headers,
    )
    bundle.comp_plan = get_success_data(res)
    return bundle


def approve_plan(bundle: CompPlanBundle) -> CompPlanBundle:
    """POST .../approve using the bundle's Approver (distinct from Manager)."""
    res = api_client.approve_comp_plan(
        bundle.cycle["id"], bundle.comp_plan["id"], bundle.approver.headers,
    )
    bundle.comp_plan = get_success_data(res)
    return bundle


# ===========================================================================
# Tier 6 — PIP plumbing (relies on clock advance for pass/fail)
# ===========================================================================
def setup_active_pip_case(
        triggering_rating: str = "NEEDS_IMPROVEMENT",
        subject_department: str = "Eng",
        subject_job_level: int = 4,
) -> Tuple[ReviewCaseBundle, Dict[str, Any]]:
    """Drive a subject to ACTIVE PIP via NEEDS_IMPROVEMENT or UNSATISFACTORY
    calibration. Returns (ReviewCaseBundle, PIPCase).

    PRD §3.6: "A PIPCase is created (in ACTIVE) for any subject whose
    calibrated final_rating is NEEDS_IMPROVEMENT or UNSATISFACTORY." The
    duration is server-pinned: 60 days for NEEDS_IMPROVEMENT, 30 for
    UNSATISFACTORY.
    """
    assert triggering_rating in ("NEEDS_IMPROVEMENT", "UNSATISFACTORY")
    bundle = setup_finalized_review_case(
        final_rating=triggering_rating,
        subject_department=subject_department,
        subject_job_level=subject_job_level,
    )
    # Locate the auto-created PIPCase for the subject.
    pips, _ = _list_pip_cases_for_subject(
        bundle.cycle["id"], bundle.subject["id"], bundle.hrbp.headers,
    )
    assert pips, (
        "Setup expected an ACTIVE PIPCase to be auto-created by "
        "calibration commit per PRD §3.5/§3.6, found none."
    )
    return bundle, pips[0]


def _list_pip_cases_for_subject(cycle_id: str,
                                subject_employee_id: str,
                                headers: Dict[str, str]
                                ) -> Tuple[List[Dict[str, Any]], Any]:
    res = api_client.list_pip_cases(
        cycle_id, headers,
        params={"subject_employee_id": subject_employee_id},
    )
    data = get_success_data(res)
    if isinstance(data, list):
        return data, None
    # Some implementations wrap list responses under {"data": [...]} —
    # the validators already unwrap that, but be defensive.
    return data if isinstance(data, list) else [], None


def advance_clock_past(ends_at: str,
                       seconds_after: int = 0) -> Dict[str, Any]:
    """Advance the logical clock to >= the supplied ISO instant.

    PRD §2.13: the clock only moves forward; PRD §3.6: PIP pass/fail
    requires clock_now() >= ends_at.
    """
    target_dt = datetime.fromisoformat(ends_at.replace("Z", "+00:00"))
    if seconds_after:
        target_dt = target_dt + timedelta(seconds=seconds_after)
    iso = target_dt.astimezone(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z",
    )
    res = api_client.advance_clock(
        advance_clock_payload(iso), TEST_USERS["admin_headers"],
    )
    return get_success_data(res)


# ===========================================================================
# Math helpers — let tests assert calculated values without re-deriving
# the formula by hand. Each helper implements the PRD-pinned formula.
# ===========================================================================
def expected_merit_increase_cents(*,
                                  pinned_base_salary_cents: int,
                                  cadence: str,
                                  final_rating: str,
                                  promotion_to_level: Optional[int],
                                  current_job_level: int,
                                  employee_on_pip: bool) -> int:
    """PRD §3.7 merit_increase_amount formula.

    Per §3.7: SEMI_ANNUAL halves each annual cell by integer division
    (floor); raw merit = floor(base_salary * pct / 100); promotion bump
    of +5% applies only when promotion_to_level is set AND rating in
    {OUTSTANDING, EXCEEDS}; if employee.status == ON_PIP the result is 0
    regardless of any other input.
    """
    if employee_on_pip:
        return 0
    if cadence == "ANNUAL":
        pct = ANNUAL_MERIT_PCT[final_rating]
    elif cadence == "SEMI_ANNUAL":
        pct = semi_annual_merit_pct(final_rating)
    else:
        raise ValueError(f"Unknown cadence: {cadence}")
    raw = (pinned_base_salary_cents * pct) // 100
    if (promotion_to_level is not None
            and promotion_to_level == current_job_level + 1
            and final_rating in ("OUTSTANDING", "EXCEEDS")):
        raw += (pinned_base_salary_cents * PROMO_BUMP_PCT) // 100
    return raw


def expected_equity_refresh_units(*,
                                  job_level: int,
                                  cadence: str,
                                  final_rating: str,
                                  promotion_to_level: Optional[int],
                                  employee_on_pip: bool) -> int:
    """PRD §3.7 equity_refresh_amount formula.

    Canonical evaluation order (PRD §3.7, §2.9): multiply base grant by
    cadence multiplier, round_half_up to whole units; then if a valid
    promotion bump applies, add floor(0.25 * next_level_grant). The PIP
    gate forces 0 if the subject is ON_PIP.
    """
    if employee_on_pip:
        return 0
    base = equity_base_units(job_level, final_rating)
    multiplied = base * CADENCE_MULTIPLIER[cadence]
    # round_half_up to integer
    rounded_base = int(multiplied + 0.5) if multiplied >= 0 else -int(-multiplied + 0.5)
    bump = 0
    if (promotion_to_level is not None
            and promotion_to_level == job_level + 1
            and final_rating in ("OUTSTANDING", "EXCEEDS")):
        next_level_grant = equity_base_units(promotion_to_level,
                                             final_rating)
        bump = int(next_level_grant * PROMO_BUMP_FACTOR)  # floor
    return rounded_base + bump


def expected_weighted_goal_score(weights: List[int],
                                 scores: List[int]) -> float:
    """PRD §3.3: sum(weight * manager_score) / 100, round_half_up to 2
    decimals. Uses Python's bankers-rounded `round` is wrong; we use a
    half-up rounding to comply with PRD §3.3 / §2.9.
    """
    raw = sum(w * s for w, s in zip(weights, scores)) / 100.0
    # round_half_up at 2dp
    return _round_half_up(raw, 2)


def _round_half_up(value: float, ndigits: int) -> float:
    """Banker-free round-half-up to ndigits."""
    quantum = 10 ** ndigits
    if value >= 0:
        return int(value * quantum + 0.5) / quantum
    return -int(-value * quantum + 0.5) / quantum


__all__ = [
    "EmployeeBundle",
    "ReviewCaseBundle",
    "CycleBundle",
    "DepartmentCalibrationBundle",
    "CompPlanBundle",
    "create_employee_with_role",
    "create_active_employee",
    "create_open_cycle",
    "add_goals_summing_to_100",
    "attach_two_submitted_feedback_requests",
    "setup_submittable_review_case",
    "submit_review_case",
    "finalize_review_case_via_calibration",
    "setup_finalized_review_case",
    "setup_department_with_locked_cases",
    "attach_calibration_session",
    "create_approver_for",
    "setup_draft_comp_plan",
    "propose_plan",
    "approve_plan",
    "setup_active_pip_case",
    "advance_clock_past",
    "expected_merit_increase_cents",
    "expected_equity_refresh_units",
    "expected_weighted_goal_score",
]
