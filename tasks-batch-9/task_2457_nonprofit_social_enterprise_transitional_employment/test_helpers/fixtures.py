"""Composite setup helpers.

Each helper drives the API through a real sequence of documented operations and
returns the rows it created, so a test can start from a mid-lifecycle state
without re-inventing the chain that gets there.

Every helper uses ``get_success_data`` for its setup calls: setup is not the
thing under test, so a failure there should read as a setup failure.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import factories as build
from .api_client import ApiClient
from .constants import (
    CLOCK_OCT_01,
    CLOCK_SEP_07,
    CLOCK_SEP_07_EVENING,
    CLOCK_SEP_14_EVENING,
    CLOCK_SEP_15,
)
from .test_users import (
    CASE_MANAGER_USER_ID,
    JOB_COACH_USER_ID,
    SECOND_JOB_COACH_USER_ID,
    make_case_manager_headers,
    make_employer_partner_headers,
    make_intake_specialist_headers,
    make_job_coach_headers,
    make_program_director_headers,
    make_referral_partner_headers,
)
from .types import AllocationBasis, ReviewDecision, ScreeningDecision

CLOCK_SEP_08_EVENING = "2026-09-08T20:00:00Z"

# The second candidate used whenever a scenario needs two trainees on one line.
SECOND_CANDIDATE_BARRIERS = ["DISABILITY", "LIMITED_ENGLISH", "YOUTH_AGING_OUT"]


# ---------------------------------------------------------------------------
# Single-step helpers
# ---------------------------------------------------------------------------


def set_clock(api: ApiClient, instant: str) -> str:
    """Move the logical clock and return the instant the server reports back."""
    data = get_success_data(api.set_clock(instant, make_program_director_headers()))
    return data["current_utc"]


def read_business_line(api: ApiClient, business_line_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_business_line(business_line_id, make_program_director_headers())
    )


def read_referral(api: ApiClient, referral_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_referral(referral_id, make_intake_specialist_headers())
    )


def read_referral_partner(api: ApiClient, referral_partner_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_referral_partner(referral_partner_id, make_program_director_headers())
    )


def read_participant(api: ApiClient, participant_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_participant(participant_id, make_case_manager_headers())
    )


def read_work_shift(api: ApiClient, work_shift_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_work_shift(work_shift_id, make_program_director_headers())
    )


def read_shift_assignment(api: ApiClient, shift_assignment_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_shift_assignment(shift_assignment_id, make_case_manager_headers())
    )


def read_support_activity(api: ApiClient, support_activity_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_support_activity(support_activity_id, make_program_director_headers())
    )


def read_employer(api: ApiClient, employer_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_employer(employer_id, make_program_director_headers())
    )


def read_placement(api: ApiClient, placement_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_placement(placement_id, make_case_manager_headers())
    )


def read_subsidy_period(api: ApiClient, subsidy_period_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_subsidy_period(subsidy_period_id, make_program_director_headers())
    )


def read_cost_entry(api: ApiClient, cost_entry_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_cost_entry(cost_entry_id, make_program_director_headers())
    )


def business_line_version(api: ApiClient, business_line_id: str) -> int:
    """The line's current version, as a client would re-read it before enrolling."""
    return read_business_line(api, business_line_id)["version"]


def subsidy_period_version(api: ApiClient, subsidy_period_id: str) -> int:
    """The period's current version, as a client would re-read it before posting."""
    return read_subsidy_period(api, subsidy_period_id)["version"]


def list_checkpoints(
    api: ApiClient, placement_id: str, params: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    rows, _meta = validate_paginated(
        api.list_retention_checkpoints(
            placement_id, make_case_manager_headers(), params
        )
    )
    return rows


def list_placements(
    api: ApiClient, params: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    rows, _meta = validate_paginated(
        api.list_placements(make_case_manager_headers(), params)
    )
    return rows


def list_cost_entries(
    api: ApiClient, params: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    rows, _meta = validate_paginated(
        api.list_cost_entries(make_program_director_headers(), params)
    )
    return rows


def cost_entry_count(api: ApiClient, params: Optional[Dict[str, Any]] = None) -> int:
    _rows, meta = validate_paginated(
        api.list_cost_entries(make_program_director_headers(), params)
    )
    return meta["total_count"]


def participant_count(api: ApiClient, params: Optional[Dict[str, Any]] = None) -> int:
    _rows, meta = validate_paginated(
        api.list_participants(make_intake_specialist_headers(), params)
    )
    return meta["total_count"]


# ---------------------------------------------------------------------------
# Tier 1: state progression of a single entity
# ---------------------------------------------------------------------------


def create_draft_business_line(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """A candidate line in DRAFT."""
    return get_success_data(
        api.create_business_line(
            build.business_line_payload(**overrides), make_program_director_headers()
        )
    )


def create_approved_business_line(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """A line carried DRAFT -> APPROVED through the viability gate."""
    line = create_draft_business_line(api, **overrides)
    return get_success_data(
        api.review_business_line(
            line["id"],
            build.review_payload(ReviewDecision.APPROVED),
            make_program_director_headers(),
        )
    )


def create_launched_business_line(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """A line carried DRAFT -> APPROVED -> LAUNCHED, so intake posture is OPEN."""
    line = create_approved_business_line(api, **overrides)
    return get_success_data(
        api.launch_business_line(line["id"], make_program_director_headers())
    )


def create_referral_partner(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_referral_partner(
            build.referral_partner_payload(**overrides), make_program_director_headers()
        )
    )


def submit_referral(
    api: ApiClient, referral_partner_id: str, **overrides: Any
) -> Dict[str, Any]:
    """A referral submitted by the owning partner, landing in SUBMITTED."""
    return get_success_data(
        api.create_referral(
            build.referral_payload(referral_partner_id, **overrides),
            make_referral_partner_headers(referral_partner_id),
        )
    )


def screen_referral(
    api: ApiClient,
    referral_id: str,
    decision: str = ScreeningDecision.ELIGIBLE,
    intake_user_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    headers = (
        make_intake_specialist_headers(intake_user_id)
        if intake_user_id
        else make_intake_specialist_headers()
    )
    return get_success_data(
        api.screen_referral(
            referral_id, build.screening_payload(decision, **overrides), headers
        )
    )


def create_eligible_referral(
    api: ApiClient,
    referral_partner_id: str,
    candidate_reference: str = "CAND-001",
    barrier_codes: Optional[List[str]] = None,
    household_income_cents: int = 100000,
    household_size: int = 2,
    hours_available_per_week: int = 40,
) -> Dict[str, Any]:
    """A referral submitted and then screened ELIGIBLE on the same verified inputs."""
    codes = list(barrier_codes) if barrier_codes is not None else None
    referral = submit_referral(
        api,
        referral_partner_id,
        candidate_reference=candidate_reference,
        household_income_cents=household_income_cents,
        household_size=household_size,
        hours_available_per_week=hours_available_per_week,
        **({"declared_barrier_codes": codes} if codes is not None else {}),
    )
    screening_overrides: Dict[str, Any] = {
        "verified_household_income_cents": household_income_cents,
        "verified_household_size": household_size,
        "verified_hours_available_per_week": hours_available_per_week,
    }
    if codes is not None:
        screening_overrides["verified_barrier_codes"] = codes
    return screen_referral(
        api, referral["id"], ScreeningDecision.ELIGIBLE, **screening_overrides
    )


def create_open_subsidy_period(
    api: ApiClient, business_line_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_subsidy_period(
            build.subsidy_period_payload(business_line_id, **overrides),
            make_program_director_headers(),
        )
    )


def enroll_participant(
    api: ApiClient,
    business_line_id: str,
    referral_id: str,
    expected_business_line_version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Enroll an ELIGIBLE referral, quoting the line's freshly re-read version."""
    version = (
        expected_business_line_version
        if expected_business_line_version is not None
        else business_line_version(api, business_line_id)
    )
    return get_success_data(
        api.create_participant(
            build.participant_payload(referral_id, business_line_id, version, **overrides),
            make_intake_specialist_headers(),
        )
    )


def create_work_shift(
    api: ApiClient, business_line_id: str, starts_at: str, ends_at: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_work_shift(
            build.work_shift_payload(business_line_id, starts_at, ends_at, **overrides),
            make_program_director_headers(),
        )
    )


def seat_participant(
    api: ApiClient, work_shift_id: str, participant_id: str
) -> Dict[str, Any]:
    return get_success_data(
        api.create_shift_assignment(
            build.shift_assignment_payload(work_shift_id, participant_id),
            make_case_manager_headers(),
        )
    )


def complete_assignment(
    api: ApiClient, shift_assignment_id: str, actual_hours: float = 12.000, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.complete_shift_assignment(
            shift_assignment_id,
            build.completion_payload(actual_hours, **overrides),
            make_case_manager_headers(),
        )
    )


def release_assignment(api: ApiClient, shift_assignment_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.release_shift_assignment(shift_assignment_id, make_case_manager_headers())
    )


def plan_support_activity(
    api: ApiClient, participant_id: str, planner_role: str = "JobCoach", **overrides: Any
) -> Dict[str, Any]:
    headers = (
        make_job_coach_headers()
        if planner_role == "JobCoach"
        else make_case_manager_headers()
    )
    return get_success_data(
        api.create_support_activity(
            build.support_activity_payload(participant_id, **overrides), headers
        )
    )


def deliver_support_activity(
    api: ApiClient, support_activity_id: str, coach_user_id: str = JOB_COACH_USER_ID
) -> Dict[str, Any]:
    return get_success_data(
        api.deliver_support_activity(
            support_activity_id, make_job_coach_headers(coach_user_id)
        )
    )


def deliver_new_support_activity(
    api: ApiClient,
    participant_id: str,
    coach_user_id: str = JOB_COACH_USER_ID,
    **overrides: Any,
) -> Dict[str, Any]:
    """Plan and then deliver one support activity in a single step."""
    activity = plan_support_activity(api, participant_id, **overrides)
    return deliver_support_activity(api, activity["id"], coach_user_id)


def certify_readiness(
    api: ApiClient, participant_id: str, coach_user_id: str = JOB_COACH_USER_ID
) -> Dict[str, Any]:
    return get_success_data(
        api.certify_readiness(participant_id, make_job_coach_headers(coach_user_id))
    )


def graduate_participant(
    api: ApiClient,
    participant_id: str,
    case_manager_user_id: str = CASE_MANAGER_USER_ID,
) -> Dict[str, Any]:
    return get_success_data(
        api.graduate_participant(
            participant_id, make_case_manager_headers(case_manager_user_id)
        )
    )


def re_enter_participant(
    api: ApiClient, participant_id: str, wage_cents_per_hour: int = 1700
) -> Dict[str, Any]:
    return get_success_data(
        api.re_enter_participant(
            participant_id,
            build.re_entry_payload(wage_cents_per_hour=wage_cents_per_hour),
            make_intake_specialist_headers(),
        )
    )


def create_employer(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_employer(
            build.employer_payload(**overrides), make_program_director_headers()
        )
    )


def create_placement(
    api: ApiClient, participant_id: str, employer_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_placement(
            build.placement_payload(participant_id, employer_id, **overrides),
            make_case_manager_headers(),
        )
    )


def post_cost_entry(
    api: ApiClient, subsidy_period_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Post a manual entry, quoting the period's freshly re-read version."""
    version = overrides.pop(
        "expected_subsidy_period_version", subsidy_period_version(api, subsidy_period_id)
    )
    return get_success_data(
        api.create_cost_entry(
            build.cost_entry_payload(subsidy_period_id, version, **overrides),
            make_program_director_headers(),
        )
    )


def close_subsidy_period(
    api: ApiClient,
    subsidy_period_id: str,
    allocation_basis: str = AllocationBasis.HOURS,
    revenue_cents: int = 250000,
) -> Dict[str, Any]:
    return get_success_data(
        api.close_subsidy_period(
            subsidy_period_id,
            build.period_close_payload(allocation_basis, revenue_cents),
            make_program_director_headers(),
        )
    )


def confirm_checkpoint(
    api: ApiClient,
    checkpoint_id: str,
    employer_id: str,
    still_employed: bool = True,
    verified_wage_cents_per_hour: Optional[int] = 1900,
) -> Dict[str, Any]:
    return get_success_data(
        api.confirm_retention_checkpoint(
            checkpoint_id,
            build.checkpoint_confirmation_payload(
                still_employed, verified_wage_cents_per_hour
            ),
            make_employer_partner_headers(employer_id),
        )
    )


def separate_placement(
    api: ApiClient,
    placement_id: str,
    employer_id: str,
    separation_type: str = "VOLUNTARY",
    separation_date: str = "2026-10-15T00:00:00Z",
) -> Dict[str, Any]:
    return get_success_data(
        api.separate_placement(
            placement_id,
            build.separation_payload(separation_type, separation_date),
            make_employer_partner_headers(employer_id),
        )
    )


# ---------------------------------------------------------------------------
# Tier 2: the enrolled-trainee program, the backbone of most scenarios
# ---------------------------------------------------------------------------


def enrolled_participant_program(
    api: ApiClient,
    clock: str = CLOCK_SEP_07,
    line_overrides: Optional[Dict[str, Any]] = None,
    partner_overrides: Optional[Dict[str, Any]] = None,
    period_overrides: Optional[Dict[str, Any]] = None,
    participant_overrides: Optional[Dict[str, Any]] = None,
    with_period: bool = True,
) -> Dict[str, Any]:
    """Launched line, TIER_1 partner, ELIGIBLE referral, OPEN period, one trainee.

    Returns a dict keyed ``business_line``, ``partner``, ``referral``,
    ``subsidy_period`` (None when ``with_period`` is False) and ``participant``.
    """
    set_clock(api, clock)
    line = create_launched_business_line(api, **(line_overrides or {}))
    partner = create_referral_partner(api, **(partner_overrides or {}))
    referral = create_eligible_referral(api, partner["id"])
    period = (
        create_open_subsidy_period(api, line["id"], **(period_overrides or {}))
        if with_period
        else None
    )
    participant = enroll_participant(
        api, line["id"], referral["id"], **(participant_overrides or {})
    )
    return {
        "business_line": line,
        "partner": partner,
        "referral": referral,
        "subsidy_period": period,
        "participant": participant,
    }


def add_second_referral(
    api: ApiClient,
    program: Dict[str, Any],
    candidate_reference: str = "CAND-002",
    hours_available_per_week: int = 36,
) -> Dict[str, Any]:
    """A second ELIGIBLE referral on the same partner, deliberately left unenrolled."""
    referral = create_eligible_referral(
        api,
        program["partner"]["id"],
        candidate_reference=candidate_reference,
        barrier_codes=SECOND_CANDIDATE_BARRIERS,
        hours_available_per_week=hours_available_per_week,
    )
    program["second_referral"] = referral
    return referral


def add_second_participant(
    api: ApiClient,
    program: Dict[str, Any],
    candidate_reference: str = "CAND-002",
    wage_cents_per_hour: int = 1725,
    hours_available_per_week: int = 36,
) -> Dict[str, Any]:
    """A second trainee on the same line, enrolled against a re-read line version."""
    referral = add_second_referral(
        api,
        program,
        candidate_reference=candidate_reference,
        hours_available_per_week=hours_available_per_week,
    )
    participant = enroll_participant(
        api,
        program["business_line"]["id"],
        referral["id"],
        wage_cents_per_hour=wage_cents_per_hour,
    )
    program["second_participant"] = participant
    return participant


# ---------------------------------------------------------------------------
# Tier 3: lifecycle shortcuts
# ---------------------------------------------------------------------------


def completed_shift_program(
    api: ApiClient,
    actual_hours: float = 12.000,
    completion_overrides: Optional[Dict[str, Any]] = None,
    **program_kwargs: Any,
) -> Dict[str, Any]:
    """One trainee who has worked a full twelve-hour shift on 2026-09-07.

    The completion auto-posts a TRAINEE_WAGES entry into the open September
    period and closes the shift, so the ledger is live when this returns.
    """
    program = enrolled_participant_program(api, **program_kwargs)
    shift = create_work_shift(
        api,
        program["business_line"]["id"],
        "2026-09-07T08:00:00Z",
        "2026-09-07T20:00:00Z",
    )
    assignment = seat_participant(api, shift["id"], program["participant"]["id"])
    set_clock(api, CLOCK_SEP_07_EVENING)
    completed = complete_assignment(
        api, assignment["id"], actual_hours, **(completion_overrides or {})
    )
    program["work_shift"] = shift
    program["assignment"] = completed
    return program


def graduated_participant_program(
    api: ApiClient, **program_kwargs: Any
) -> Dict[str, Any]:
    """One trainee carried all the way to GRADUATED.

    Two twelve-hour shifts on 2026-09-07 and 2026-09-08 supply 24.000 worked
    hours; two delivered ninety-minute job-coaching sessions supply 180 support
    minutes and two coaching sessions. ``coach-1`` certifies readiness and
    ``cm-1`` graduates, which keeps the two identities distinct.
    """
    program = completed_shift_program(api, **program_kwargs)
    second_shift = create_work_shift(
        api,
        program["business_line"]["id"],
        "2026-09-08T08:00:00Z",
        "2026-09-08T20:00:00Z",
    )
    second_assignment = seat_participant(
        api, second_shift["id"], program["participant"]["id"]
    )
    set_clock(api, CLOCK_SEP_08_EVENING)
    second_completed = complete_assignment(api, second_assignment["id"], 12.000)

    coaching = [
        deliver_new_support_activity(
            api,
            program["participant"]["id"],
            cost_cents=6000,
            duration_minutes=90,
        )
        for _ in range(2)
    ]

    certified = get_success_data(
        api.certify_readiness(
            program["participant"]["id"], make_job_coach_headers(JOB_COACH_USER_ID)
        )
    )
    graduated = get_success_data(
        api.graduate_participant(
            program["participant"]["id"], make_case_manager_headers(CASE_MANAGER_USER_ID)
        )
    )

    program["second_work_shift"] = second_shift
    program["second_assignment"] = second_completed
    program["coaching_activities"] = coaching
    program["certified_participant"] = certified
    program["participant"] = graduated
    return program


def two_week_shift_program(api: ApiClient, **program_kwargs: Any) -> Dict[str, Any]:
    """One trainee with 24.000 worked hours banked across two ISO weeks.

    Twelve hours on Monday 2026-09-07 and twelve more on Monday 2026-09-14, so
    neither week comes close to the weekly cap. The clock is left at
    2026-09-14T20:00:00Z, still inside the open September period.
    """
    program = completed_shift_program(api, **program_kwargs)
    second_shift = create_work_shift(
        api,
        program["business_line"]["id"],
        "2026-09-14T08:00:00Z",
        "2026-09-14T20:00:00Z",
    )
    second_assignment = seat_participant(
        api, second_shift["id"], program["participant"]["id"]
    )
    set_clock(api, CLOCK_SEP_14_EVENING)
    program["second_work_shift"] = second_shift
    program["second_assignment"] = complete_assignment(
        api, second_assignment["id"], 12.000
    )
    return program


def ready_for_graduation_program(
    api: ApiClient, coaching_sessions: int = 2, **program_kwargs: Any
) -> Dict[str, Any]:
    """A trainee holding 24.000 hours and two coaching sessions, readiness certified.

    ``coach-1`` delivers the coaching and certifies, which leaves the
    certifying identity free to be contrasted with the graduating one. The
    clock is advanced to 2026-09-15T00:00:00Z so graduation lands on a clean
    day boundary.
    """
    program = two_week_shift_program(api, **program_kwargs)
    program["coaching_activities"] = [
        deliver_new_support_activity(
            api, program["participant"]["id"], cost_cents=6000, duration_minutes=90
        )
        for _ in range(coaching_sessions)
    ]
    program["participant"] = certify_readiness(api, program["participant"]["id"])
    set_clock(api, CLOCK_SEP_15)
    return program


def mid_september_graduate_program(
    api: ApiClient, **program_kwargs: Any
) -> Dict[str, Any]:
    """A trainee graduated by ``cm-1`` at 2026-09-15T00:00:00Z."""
    program = ready_for_graduation_program(api, **program_kwargs)
    program["participant"] = graduate_participant(api, program["participant"]["id"])
    return program


def two_graduates_program(api: ApiClient) -> Dict[str, Any]:
    """Two trainees carried side by side to GRADUATED on the same line.

    Both share the two twelve-hour shifts, so both bank 24.000 hours. Each is
    coached and certified by a different job coach and both are graduated by
    ``cm-1``, so no graduation collides with its own certifier.
    """
    program = enrolled_participant_program(api)
    add_second_participant(api, program, wage_cents_per_hour=1650)
    first_id = program["participant"]["id"]
    second_id = program["second_participant"]["id"]

    shifts = []
    for starts_at, ends_at, evening in (
        ("2026-09-07T08:00:00Z", "2026-09-07T20:00:00Z", CLOCK_SEP_07_EVENING),
        ("2026-09-14T08:00:00Z", "2026-09-14T20:00:00Z", CLOCK_SEP_14_EVENING),
    ):
        shift = create_work_shift(
            api, program["business_line"]["id"], starts_at, ends_at
        )
        seats = [
            seat_participant(api, shift["id"], first_id),
            seat_participant(api, shift["id"], second_id),
        ]
        set_clock(api, evening)
        for seat in seats:
            complete_assignment(api, seat["id"], 12.000)
        shifts.append(shift)

    for participant_id, coach_user_id in (
        (first_id, JOB_COACH_USER_ID),
        (second_id, SECOND_JOB_COACH_USER_ID),
    ):
        for _ in range(2):
            deliver_new_support_activity(
                api,
                participant_id,
                coach_user_id=coach_user_id,
                cost_cents=6000,
                duration_minutes=90,
            )
        certify_readiness(api, participant_id, coach_user_id)

    set_clock(api, CLOCK_SEP_15)
    program["work_shifts"] = shifts
    program["participant"] = graduate_participant(api, first_id)
    program["second_participant"] = graduate_participant(api, second_id)
    return program


def placed_participant_program(
    api: ApiClient,
    employer_overrides: Optional[Dict[str, Any]] = None,
    placement_overrides: Optional[Dict[str, Any]] = None,
    **program_kwargs: Any,
) -> Dict[str, Any]:
    """A graduate placed with an outside employer, with the four checkpoints read back.

    The employer floor is 1800 and the placement wage 1900, which clears both
    the employer floor and the ten-percent progression floor above the frozen
    graduation wage of 1650.
    """
    program = graduated_participant_program(api, **program_kwargs)
    employer = create_employer(
        api,
        **{
            "organization_name": "Northgate Logistics",
            "industry_code": "LOG",
            "min_starting_wage_cents_per_hour": 1800,
            **(employer_overrides or {}),
        },
    )
    placement = create_placement(
        api,
        program["participant"]["id"],
        employer["id"],
        **(placement_overrides or {}),
    )
    program["employer"] = employer
    program["placement"] = placement
    program["checkpoints"] = list_checkpoints(api, placement["id"])
    return program


def re_entry_eligible_program(api: ApiClient, **program_kwargs: Any) -> Dict[str, Any]:
    """A participant returned to RE_ENTRY_ELIGIBLE by an early separation.

    The separation lands 14 days after the 2026-10-01 hire date, so the
    retention outcome is FAILED_EARLY and the participant becomes re-entry
    eligible.
    """
    program = placed_participant_program(api, **program_kwargs)
    set_clock(api, "2026-10-15T00:00:00Z")
    separated = separate_placement(
        api,
        program["placement"]["id"],
        program["employer"]["id"],
        separation_type="INVOLUNTARY",
        separation_date="2026-10-15T00:00:00Z",
    )
    program["placement"] = separated
    return program


# ---------------------------------------------------------------------------
# Tier 4: accumulation and threshold targeting
# ---------------------------------------------------------------------------


def canonical_ledger_program(
    api: ApiClient, coaching_cost_cents: int = 12000, **program_kwargs: Any
) -> Dict[str, Any]:
    """The four-entry September ledger the PRD works through in prose.

    One SHARED trainee-wage entry of 19800 from a completed twelve-hour shift,
    one MISSION coaching entry, one SHARED supervision entry of 300000 and one
    BUSINESS materials entry of 40000.
    """
    program = completed_shift_program(api, **program_kwargs)
    period_id = program["subsidy_period"]["id"]
    coaching = deliver_new_support_activity(
        api,
        program["participant"]["id"],
        cost_cents=coaching_cost_cents,
        duration_minutes=90,
    )
    supervision = post_cost_entry(
        api,
        period_id,
        category="SUPERVISION",
        classification="SHARED",
        amount_cents=300000,
    )
    materials = post_cost_entry(
        api,
        period_id,
        category="MATERIALS",
        classification="BUSINESS",
        amount_cents=40000,
    )
    program["coaching_activity"] = coaching
    program["supervision_entry"] = supervision
    program["materials_entry"] = materials
    return program


def quality_closed_intake_program(api: ApiClient, **program_kwargs: Any) -> Dict[str, Any]:
    """A launched line whose intake posture has closed on quality incidents alone.

    A single completion carrying six defects and four complaints takes the
    line's quality incident count to exactly ten, which closes intake while the
    line is still LAUNCHED with slots to spare.

    A second ELIGIBLE referral is left unenrolled so that a caller can attempt an
    enrollment against the closed posture.
    """
    program = enrolled_participant_program(api, **program_kwargs)
    add_second_referral(api, program)
    shift = create_work_shift(
        api,
        program["business_line"]["id"],
        "2026-09-07T08:00:00Z",
        "2026-09-07T20:00:00Z",
    )
    assignment = seat_participant(api, shift["id"], program["participant"]["id"])
    set_clock(api, CLOCK_SEP_07_EVENING)
    completed = complete_assignment(
        api,
        assignment["id"],
        12.000,
        quality_defect_count=6,
        customer_complaint_count=4,
    )
    program["work_shift"] = shift
    program["assignment"] = completed
    return program


def weekly_hours_ladder_program(api: ApiClient, **program_kwargs: Any) -> Dict[str, Any]:
    """Four shifts in the ISO week of 2026-09-07 sized 12, 12, 4 and 0.5 hours.

    Seating the first two commits 24.000 hours, so the four-hour shift lands
    exactly on the weekly cap and the half-hour shift steps over it.
    """
    program = enrolled_participant_program(api, with_period=False, **program_kwargs)
    line_id = program["business_line"]["id"]
    monday = create_work_shift(
        api, line_id, "2026-09-07T08:00:00Z", "2026-09-07T20:00:00Z"
    )
    tuesday = create_work_shift(
        api, line_id, "2026-09-08T08:00:00Z", "2026-09-08T20:00:00Z"
    )
    wednesday = create_work_shift(
        api, line_id, "2026-09-09T08:00:00Z", "2026-09-09T12:00:00Z"
    )
    thursday = create_work_shift(
        api, line_id, "2026-09-10T08:00:00Z", "2026-09-10T08:30:00Z"
    )
    program["monday_shift"] = monday
    program["tuesday_shift"] = tuesday
    program["wednesday_shift"] = wednesday
    program["thursday_shift"] = thursday
    program["monday_assignment"] = seat_participant(
        api, monday["id"], program["participant"]["id"]
    )
    program["tuesday_assignment"] = seat_participant(
        api, tuesday["id"], program["participant"]["id"]
    )
    return program


def rest_buffer_program(api: ApiClient) -> Dict[str, Any]:
    """Three shifts on 2026-09-07 whose gaps are exactly 60 and exactly 59 minutes."""
    program = enrolled_participant_program(
        api, line_overrides={"supervisor_capacity": 3}, with_period=False
    )
    line_id = program["business_line"]["id"]
    shift_a = create_work_shift(
        api, line_id, "2026-09-07T08:00:00Z", "2026-09-07T12:00:00Z"
    )
    shift_b = create_work_shift(
        api, line_id, "2026-09-07T13:00:00Z", "2026-09-07T15:00:00Z"
    )
    shift_c = create_work_shift(
        api, line_id, "2026-09-07T15:59:00Z", "2026-09-07T17:00:00Z"
    )
    program["shift_a"] = shift_a
    program["shift_b"] = shift_b
    program["shift_c"] = shift_c
    program["assignment_a"] = seat_participant(
        api, shift_a["id"], program["participant"]["id"]
    )
    return program


def supervision_capacity_program(api: ApiClient) -> Dict[str, Any]:
    """Two trainees and three shifts on a line whose supervisor capacity is one.

    Shift X runs 08:00-12:00, Y overlaps it from 10:00-14:00 and Z merely
    touches it from 12:00-16:00.
    """
    program = enrolled_participant_program(
        api, line_overrides={"supervisor_capacity": 1}, with_period=False
    )
    add_second_participant(api, program)
    line_id = program["business_line"]["id"]
    shift_x = create_work_shift(
        api, line_id, "2026-09-07T08:00:00Z", "2026-09-07T12:00:00Z"
    )
    shift_y = create_work_shift(
        api,
        line_id,
        "2026-09-07T10:00:00Z",
        "2026-09-07T14:00:00Z",
        supervisor_user_id="sup-2",
    )
    shift_z = create_work_shift(
        api,
        line_id,
        "2026-09-07T12:00:00Z",
        "2026-09-07T16:00:00Z",
        supervisor_user_id="sup-2",
    )
    program["shift_x"] = shift_x
    program["shift_y"] = shift_y
    program["shift_z"] = shift_z
    program["assignment_x"] = seat_participant(
        api, shift_x["id"], program["participant"]["id"]
    )
    return program


# ---------------------------------------------------------------------------
# Tier 5: finalisation and terminal state
# ---------------------------------------------------------------------------


def closed_period_program(
    api: ApiClient,
    allocation_basis: str = AllocationBasis.HOURS,
    revenue_cents: int = 250000,
    close_clock: str = CLOCK_OCT_01,
    **program_kwargs: Any,
) -> Dict[str, Any]:
    """The canonical four-entry ledger, closed on 2026-10-01."""
    program = canonical_ledger_program(api, **program_kwargs)
    set_clock(api, close_clock)
    program["subsidy_period"] = close_subsidy_period(
        api, program["subsidy_period"]["id"], allocation_basis, revenue_cents
    )
    return program


def retained_placement_program(api: ApiClient, **program_kwargs: Any) -> Dict[str, Any]:
    """A placement confirmed at 30 and 90 days, ready for the 180-day answer."""
    program = placed_participant_program(api, **program_kwargs)
    set_clock(api, "2027-03-30T00:00:00Z")
    checkpoints = program["checkpoints"]
    confirm_checkpoint(api, checkpoints[0]["id"], program["employer"]["id"])
    confirm_checkpoint(api, checkpoints[1]["id"], program["employer"]["id"])
    return program
