"""Composite state builders.

Every builder drives the public API from an empty database, because the harness
relaunches the service before each test. Builders use the lenient
``get_success_data`` so that a setup step's exact 2xx code never masks the
assertion the test is actually making.

The chains mirror the PRD's pipelines: intake -> submit -> screen -> committee
referral -> committee reviews -> selection decision for a household; raw land ->
title -> environmental -> utilities for a site; schedule -> open -> reserve ->
confirm -> lock -> check in -> complete for a shift; originate -> underwrite ->
approve -> close -> lien for a loan.
"""

from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from . import constants as C
from . import factories as F
from .test_users import (
    ADMIN,
    APPROVER,
    COMMITTEE_ALICE,
    COMMITTEE_BRUNO,
    COORDINATOR,
    CREW_LEAD,
    OFFICER,
    make_applicant_headers,
    make_volunteer_headers,
)

# ---------------------------------------------------------------------------
# Fresh-version readers. Cascades bump a parent's version silently, so every
# optimistic-concurrency call reads its parent immediately beforehand rather
# than reusing a version captured earlier in the test.
# ---------------------------------------------------------------------------


def program_version(api, program_id: str) -> int:
    return get_success_data(api.get_program(program_id, headers=ADMIN))["version"]


def household_version(api, household_id: str, headers: Optional[Dict[str, str]] = None) -> int:
    return get_success_data(api.get_household(household_id, headers=headers or COORDINATOR))["version"]


def shift_version(api, shift_id: str, headers: Optional[Dict[str, str]] = None) -> int:
    return get_success_data(api.get_shift(shift_id, headers=headers or CREW_LEAD))["version"]


def advance_clock(api, current_utc: str) -> Dict[str, Any]:
    return get_success_data(api.set_clock(current_utc, headers=ADMIN))


# ---------------------------------------------------------------------------
# Program
# ---------------------------------------------------------------------------


def setup_program(api, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_program(F.program_payload(**overrides), headers=ADMIN))


# ---------------------------------------------------------------------------
# Household pipeline
# ---------------------------------------------------------------------------


def setup_household(api, program_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_household(F.household_payload(program_id, **overrides), headers=COORDINATOR))


def add_member(
    api, household_id: str, headers: Optional[Dict[str, str]] = None, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_member(F.member_payload(household_id, **overrides), headers=headers or COORDINATOR)
    )


def submit_household(api, household_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api.submit_household(household_id, F.submit_payload(), headers=headers or COORDINATOR)
    )


def screen_household(api, household_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.screen_household(household_id, F.screen_payload(**overrides), headers=COORDINATOR)
    )


def refer_household(api, household_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.refer_to_committee(household_id, F.referral_payload(**overrides), headers=COORDINATOR)
    )


def file_review_set(
    api,
    household_id: str,
    score: float = 80,
    reviewers: Sequence[Dict[str, str]] = (COMMITTEE_ALICE, COMMITTEE_BRUNO),
    willingness_score: Optional[float] = None,
    willingness_recommendation: Optional[str] = None,
    documented_reason: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """File one review per dimension for each reviewer, meeting a quorum of two.

    Quorum is counted per scoring dimension independently, so every reviewer
    files on all three of NEED, ABILITY and WILLINGNESS.
    """
    reviews: List[Dict[str, Any]] = []
    for reviewer in reviewers:
        for dimension in C.ALL_DIMENSIONS:
            payload = F.review_payload(household_id, dimension, score)
            if dimension == C.DIMENSION_WILLINGNESS:
                if willingness_score is not None:
                    payload["score"] = willingness_score
                if willingness_recommendation is not None:
                    payload["recommendation"] = willingness_recommendation
                if documented_reason is not None:
                    payload["documented_reason"] = documented_reason
            reviews.append(get_success_data(api.create_review(payload, headers=reviewer)))
    return reviews


def decide_selection(api, household_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.record_selection_decision(household_id, F.selection_decision_payload(**overrides), headers=ADMIN)
    )


def setup_referred_household(
    api,
    program_id: str,
    household_overrides: Optional[Dict[str, Any]] = None,
    member_specs: Optional[Sequence[Dict[str, Any]]] = None,
    screen_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """An intake carried through submission and screening into committee review."""
    household = setup_household(api, program_id, **(household_overrides or {}))
    specs = list(member_specs) if member_specs is not None else [{}]
    members = [add_member(api, household["id"], **spec) for spec in specs]
    submit_household(api, household["id"])
    screen_household(api, household["id"], **(screen_overrides or {}))
    household = refer_household(api, household["id"])
    return {"household": household, "members": members}


def setup_selected_household(
    api,
    program_id: str,
    household_overrides: Optional[Dict[str, Any]] = None,
    member_specs: Optional[Sequence[Dict[str, Any]]] = None,
    screen_overrides: Optional[Dict[str, Any]] = None,
    review_score: float = 80,
    willingness_score: Optional[float] = None,
) -> Dict[str, Any]:
    """A household carried all the way to a documented committee decision."""
    built = setup_referred_household(
        api,
        program_id,
        household_overrides=household_overrides,
        member_specs=member_specs,
        screen_overrides=screen_overrides,
    )
    reviews = file_review_set(
        api, built["household"]["id"], score=review_score, willingness_score=willingness_score
    )
    household = decide_selection(api, built["household"]["id"])
    return {"household": household, "members": built["members"], "reviews": reviews}


def setup_denied_household(
    api,
    program_id: str,
    household_overrides: Optional[Dict[str, Any]] = None,
    member_specs: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """A household denied by a documented willingness veto."""
    built = setup_referred_household(
        api, program_id, household_overrides=household_overrides, member_specs=member_specs
    )
    reviews = file_review_set(
        api,
        built["household"]["id"],
        willingness_score=20,
        willingness_recommendation=C.RECOMMENDATION_VETO,
        documented_reason="Family declined the partnership obligations on the record",
    )
    household = decide_selection(api, built["household"]["id"])
    return {"household": household, "members": built["members"], "reviews": reviews}


# ---------------------------------------------------------------------------
# Build sites
# ---------------------------------------------------------------------------


def setup_site(api, program_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_build_site(F.build_site_payload(program_id, **overrides), headers=ADMIN))


def advance_site(api, site_id: str, step: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.advance_readiness(site_id, F.readiness_payload(step, **overrides), headers=ADMIN))


def setup_title_clear_site(api, program_id: str, **overrides: Any) -> Dict[str, Any]:
    site = setup_site(api, program_id, **overrides)
    return advance_site(api, site["id"], C.STEP_TITLE)


def setup_env_cleared_site(api, program_id: str, **overrides: Any) -> Dict[str, Any]:
    site = setup_title_clear_site(api, program_id, **overrides)
    return advance_site(api, site["id"], C.STEP_ENVIRONMENTAL)


def setup_ready_site(api, program_id: str, **overrides: Any) -> Dict[str, Any]:
    """A site walked RAW_LAND -> TITLE_CLEAR -> ENV_CLEARED -> READY_TO_BUILD."""
    site = setup_env_cleared_site(api, program_id, **overrides)
    return advance_site(api, site["id"], C.STEP_UTILITIES)


def start_construction(
    api,
    program_id: str,
    site_id: str,
    start_at: str = "2026-08-10T08:00:00.000Z",
    end_at: str = "2026-08-10T16:00:00.000Z",
) -> Dict[str, Any]:
    """Lock one filled shift, which is what moves a site into construction.

    READY_TO_BUILD -> UNDER_CONSTRUCTION is never an operator action; it is a
    consequence of the first shift on that site locking its roster, and a lock
    needs at least the ceiling of sixty percent of its general seats confirmed.
    """
    volunteer = setup_volunteer(api, program_id)
    shift = setup_open_shift(api, site_id, start_at=start_at, end_at=end_at, volunteer_slots=1)
    seat = reserve_volunteer_seat(api, shift["id"], volunteer["id"])
    confirm_seat(api, seat["id"])
    shift = lock_shift(api, shift["id"])
    return {"volunteer": volunteer, "shift": shift, "assignment": seat}


def complete_site(
    api,
    program_id: str,
    site_id: str,
    start_at: str = "2026-08-10T08:00:00.000Z",
    end_at: str = "2026-08-10T16:00:00.000Z",
) -> Dict[str, Any]:
    """Close the build: start construction, clear the roster, then inspect.

    The final inspection moves UNDER_CONSTRUCTION -> COMPLETED and requires that
    no shift of the site is still SCHEDULED, OPEN or LOCKED, so the shift that
    started construction is cancelled first.
    """
    built = start_construction(api, program_id, site_id, start_at=start_at, end_at=end_at)
    get_success_data(api.cancel_shift(built["shift"]["id"], F.cancellation_payload(), headers=CREW_LEAD))
    return advance_site(api, site_id, C.STEP_FINAL_INSPECTION)


# ---------------------------------------------------------------------------
# Volunteers, shifts and seats
# ---------------------------------------------------------------------------


def setup_volunteer(api, program_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_volunteer(F.volunteer_payload(program_id, **overrides), headers=CREW_LEAD))


def setup_shift(api, build_site_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_shift(F.shift_payload(build_site_id, **overrides), headers=CREW_LEAD))


def open_shift(api, shift_id: str) -> Dict[str, Any]:
    return get_success_data(api.open_shift(shift_id, headers=CREW_LEAD))


def setup_open_shift(api, build_site_id: str, **overrides: Any) -> Dict[str, Any]:
    shift = setup_shift(api, build_site_id, **overrides)
    return open_shift(api, shift["id"])


def reserve_volunteer_seat(
    api,
    shift_id: str,
    volunteer_id: str,
    role: str = C.SEAT_GENERAL,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Reserve a community seat against a freshly read shift version."""
    payload = F.assignment_payload(
        shift_id, shift_version(api, shift_id), role=role, volunteer_id=volunteer_id
    )
    return get_success_data(api.create_assignment(payload, headers=headers or CREW_LEAD))


def reserve_partner_seat(
    api, shift_id: str, household_member_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    payload = F.assignment_payload(
        shift_id,
        shift_version(api, shift_id),
        role=C.SEAT_HOMEOWNER_PARTNER,
        household_member_id=household_member_id,
    )
    return get_success_data(api.create_assignment(payload, headers=headers or CREW_LEAD))


def confirm_seat(api, assignment_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.confirm_assignment(assignment_id, headers=headers or CREW_LEAD))


def lock_shift(api, shift_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.lock_shift(shift_id, F.lock_payload(**overrides), headers=CREW_LEAD))


def check_in_seat(api, assignment_id: str) -> Dict[str, Any]:
    return get_success_data(api.check_in_assignment(assignment_id, headers=CREW_LEAD))


def complete_shift(api, shift_id: str) -> Dict[str, Any]:
    return get_success_data(api.complete_shift(shift_id, F.completion_payload(), headers=CREW_LEAD))


# ---------------------------------------------------------------------------
# The sweat equity ledger
# ---------------------------------------------------------------------------


def claim_hours(
    api,
    household_id: str,
    member_id: str,
    category: str = C.CATEGORY_CONSTRUCTION,
    hours_claimed: float = 6.0,
    work_date: str = "2026-08-01T00:00:00.000Z",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    payload = F.entry_payload(household_id, member_id, category, hours_claimed, work_date)
    return get_success_data(api.create_entry(payload, headers=headers or COORDINATOR))


def verify_hours(api, entry_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Verify a claim as somebody other than the claimant.

    The claim above is filed by the coordinator, so verification is recorded by
    the construction manager -- the identity recording the decision may not be
    the identity that claimed the hours.
    """
    return get_success_data(api.verify_entry(entry_id, F.verification_payload(), headers=headers or CREW_LEAD))


def credit_hours(api, entry_id: str) -> Dict[str, Any]:
    return get_success_data(api.credit_entry(entry_id, headers=COORDINATOR))


def setup_credited_entry(
    api,
    household_id: str,
    member_id: str,
    category: str = C.CATEGORY_CONSTRUCTION,
    hours_claimed: float = 6.0,
    work_date: str = "2026-08-01T00:00:00.000Z",
) -> Dict[str, Any]:
    """Claim, verify and credit one entry in the canonical three hops."""
    entry = claim_hours(api, household_id, member_id, category, hours_claimed, work_date)
    verify_hours(api, entry["id"])
    return credit_hours(api, entry["id"])


# ---------------------------------------------------------------------------
# Education
# ---------------------------------------------------------------------------


def setup_enrollment(api, household_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_enrollment(F.enrollment_payload(household_id, **overrides), headers=COORDINATOR)
    )


def record_module(api, enrollment_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.record_module_completion(enrollment_id, F.module_completion_payload(**overrides), headers=COORDINATOR)
    )


def setup_completed_education(api, household_id: str) -> Dict[str, Any]:
    """A single-module HOMEBUYER_CORE enrollment carried to COMPLETED."""
    enrollment = setup_enrollment(api, household_id, required_module_count=1)
    return record_module(api, enrollment["id"], outcome=C.OUTCOME_PASSED, module_code="MOD-1")


# ---------------------------------------------------------------------------
# Mortgage applications
# ---------------------------------------------------------------------------


def setup_draft_application(
    api, household_id: str, build_site_id: str, headers: Optional[Dict[str, str]] = None, **overrides: Any
) -> Dict[str, Any]:
    """Originate against a freshly read household version."""
    payload = F.application_payload(
        household_id, build_site_id, household_version(api, household_id), **overrides
    )
    return get_success_data(api.create_application(payload, headers=headers or OFFICER))


def submit_underwriting(api, application_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.submit_underwriting(application_id, headers=headers or OFFICER))


def setup_underwritten_application(api, household_id: str, build_site_id: str, **overrides: Any) -> Dict[str, Any]:
    application = setup_draft_application(api, household_id, build_site_id, **overrides)
    return submit_underwriting(api, application["id"])


def approve_application(api, application_id: str, program_id: str, **overrides: Any) -> Dict[str, Any]:
    """Approve against a freshly read program version, as the second officer.

    The officer who submitted underwriting is never the officer who approves or
    denies, so the approval is recorded by a different identity.
    """
    payload = F.approval_payload(program_version(api, program_id), **overrides)
    return get_success_data(api.approve_application(application_id, payload, headers=APPROVER))


def setup_approved_application(
    api, program_id: str, household_id: str, build_site_id: str, **overrides: Any
) -> Dict[str, Any]:
    application = setup_underwritten_application(api, household_id, build_site_id, **overrides)
    return approve_application(api, application["id"], program_id)


def close_application(api, application_id: str, closing_date: str) -> Dict[str, Any]:
    return get_success_data(
        api.close_application(application_id, F.closing_payload(closing_date), headers=APPROVER)
    )


def setup_closed_loan(
    api,
    program_id: str,
    household_id: str,
    member_id: str,
    build_site_id: str,
    closing_date: str = "2026-08-05T00:00:00.000Z",
    clock_before_close: Optional[str] = "2026-08-05T00:00:00.000Z",
) -> Dict[str, Any]:
    """Carry a selected household all the way to a recorded silent second lien.

    Closing requires four things at once: a COMPLETED build site, a completed
    and unexpired HOMEBUYER_CORE enrollment, satisfied sweat equity, and
    CLOSING_READY readiness. The lien is recorded at the logical clock instant,
    so the clock is advanced to the closing instant just before the close.
    """
    application = setup_underwritten_application(api, household_id, build_site_id)
    setup_credited_entry(api, household_id, member_id, hours_claimed=12.0)
    setup_completed_education(api, household_id)
    application = approve_application(api, application["id"], program_id)
    complete_site(api, program_id, build_site_id)
    if clock_before_close is not None:
        advance_clock(api, clock_before_close)
    return close_application(api, application["id"], closing_date)


def lien_action(api, application_id: str, action: str, effective_date: str, **overrides: Any) -> Dict[str, Any]:
    payload = F.lien_action_payload(action, effective_date, **overrides)
    return get_success_data(api.lien_action(application_id, payload, headers=APPROVER))


# ---------------------------------------------------------------------------
# Grant awards
# ---------------------------------------------------------------------------


def setup_grant(api, program_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_grant_award(F.grant_payload(program_id, **overrides), headers=ADMIN))


# ---------------------------------------------------------------------------
# Cost ledger
# ---------------------------------------------------------------------------


def add_cash_cost(api, build_site_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_cost_entry(F.cash_cost_payload(build_site_id, **overrides), headers=CREW_LEAD))


def add_in_kind_cost(api, build_site_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_cost_entry(F.in_kind_cost_payload(build_site_id, **overrides), headers=CREW_LEAD)
    )


# ---------------------------------------------------------------------------
# Entity-backed identity helpers, re-exported for convenience
# ---------------------------------------------------------------------------

__all__ = [name for name in dir() if not name.startswith("_")] + [
    "make_applicant_headers",
    "make_volunteer_headers",
]
