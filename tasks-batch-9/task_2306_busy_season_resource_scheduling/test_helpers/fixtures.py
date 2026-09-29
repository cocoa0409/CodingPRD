"""Composite setup helpers.

Every helper builds its preconditions exclusively through the public endpoints,
because each test starts against an empty store. Helpers use the lenient
``get_success_data`` reader so a setup failure surfaces as a setup error rather
than as a misleading assertion failure inside the test body.

Ownership-gated calls always present the identifier of the staff member who owns
the resource, never a stand-in identity.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .factories import (
    create_assignment_payload,
    create_availability_exception_payload,
    create_client_payload,
    create_engagement_payload,
    create_engagement_phase_payload,
    create_independence_restriction_payload,
    create_reschedule_plan_payload,
    create_review_capacity_window_payload,
    create_staff_member_payload,
    create_time_entry_payload,
    create_workload_waiver_payload,
)
from .test_users import (
    firm_admin_headers,
    independence_officer_headers,
    make_engagement_partner_headers,
    make_engagement_staff_headers,
    scheduling_manager_headers,
)
from .types import JsonDict

# ---------------------------------------------------------------------------
# Tier 1 -- single primitive steps
# ---------------------------------------------------------------------------


def set_clock(api, to_iso8601: str) -> JsonDict:
    """Move the logical clock and return the reported clock triple."""

    return get_success_data(api.set_clock(to_iso8601, firm_admin_headers()))


def create_client(api, **overrides: Any) -> JsonDict:
    payload = create_client_payload(**overrides)
    return get_success_data(api.create_client(payload, firm_admin_headers()))


def create_staff(api, **overrides: Any) -> JsonDict:
    payload = create_staff_member_payload(**overrides)
    return get_success_data(api.create_staff_member(payload, firm_admin_headers()))


def create_partner(
    api,
    full_name: str = "Pat Rowe",
    industry_specialization: str = "MANUFACTURING",
    base_weekly_cap_hours: float = 45.00,
    hourly_bill_rate: float = 400.00,
    **overrides: Any,
) -> JsonDict:
    """A domestic partner, eligible to lead an engagement."""

    return create_staff(
        api,
        full_name=full_name,
        level="PARTNER",
        service_center="DOMESTIC",
        industry_specialization=industry_specialization,
        cpa_licensed=True,
        base_weekly_cap_hours=base_weekly_cap_hours,
        hourly_bill_rate=hourly_bill_rate,
        **overrides,
    )


def create_senior(
    api,
    full_name: str = "Sam Oyelaran",
    base_weekly_cap_hours: float = 40.00,
    hourly_bill_rate: float = 180.00,
    industry_specialization: str = "MANUFACTURING",
    **overrides: Any,
) -> JsonDict:
    return create_staff(
        api,
        full_name=full_name,
        level="SENIOR",
        service_center="DOMESTIC",
        industry_specialization=industry_specialization,
        cpa_licensed=True,
        base_weekly_cap_hours=base_weekly_cap_hours,
        hourly_bill_rate=hourly_bill_rate,
        **overrides,
    )


def create_reviewer(
    api,
    full_name: str = "Mira Lindqvist",
    base_weekly_cap_hours: float = 45.00,
    hourly_bill_rate: float = 300.00,
    industry_specialization: str = "MANUFACTURING",
    **overrides: Any,
) -> JsonDict:
    """A domestic manager, so the review-capable derivation is true."""

    return create_staff(
        api,
        full_name=full_name,
        level="MANAGER",
        service_center="DOMESTIC",
        industry_specialization=industry_specialization,
        cpa_licensed=True,
        base_weekly_cap_hours=base_weekly_cap_hours,
        hourly_bill_rate=hourly_bill_rate,
        **overrides,
    )


def create_offshore_staff(
    api,
    full_name: str = "Omar Bhatt",
    level: str = "STAFF",
    base_weekly_cap_hours: float = 45.00,
    hourly_bill_rate: float = 90.00,
    cpa_licensed: bool = False,
    industry_specialization: str = "MANUFACTURING",
    **overrides: Any,
) -> JsonDict:
    return create_staff(
        api,
        full_name=full_name,
        level=level,
        service_center="OFFSHORE",
        industry_specialization=industry_specialization,
        cpa_licensed=cpa_licensed,
        base_weekly_cap_hours=base_weekly_cap_hours,
        hourly_bill_rate=hourly_bill_rate,
        **overrides,
    )


def create_engagement(api, client_id: str, partner_id: str, **overrides: Any) -> JsonDict:
    payload = create_engagement_payload(client_id, partner_id, **overrides)
    return get_success_data(api.create_engagement(payload, scheduling_manager_headers()))


def create_phase(api, engagement_id: str, **overrides: Any) -> JsonDict:
    payload = create_engagement_phase_payload(engagement_id, **overrides)
    return get_success_data(
        api.create_engagement_phase(payload, scheduling_manager_headers())
    )


def create_assignment(api, phase_id: str, staff_id: str, **overrides: Any) -> JsonDict:
    payload = create_assignment_payload(phase_id, staff_id, **overrides)
    return get_success_data(api.create_assignment(payload, scheduling_manager_headers()))


def create_availability_exception(api, staff_id: str, **overrides: Any) -> JsonDict:
    payload = create_availability_exception_payload(staff_id, **overrides)
    return get_success_data(
        api.create_availability_exception(payload, firm_admin_headers())
    )


def create_review_window(
    api, reviewer_id: str, week_start_date: str, review_capacity_hours: float
) -> JsonDict:
    payload = create_review_capacity_window_payload(
        reviewer_id,
        week_start_date=week_start_date,
        review_capacity_hours=review_capacity_hours,
    )
    return get_success_data(
        api.create_review_capacity_window(payload, firm_admin_headers())
    )


def create_restriction(api, client_id: str, staff_id: str, **overrides: Any) -> JsonDict:
    payload = create_independence_restriction_payload(client_id, staff_id, **overrides)
    return get_success_data(
        api.create_independence_restriction(payload, independence_officer_headers())
    )


def create_time_entry(api, assignment_id: str, staff_id: str, **overrides: Any) -> JsonDict:
    """Log worked hours as the staff member who owns the booking."""

    payload = create_time_entry_payload(assignment_id, **overrides)
    return get_success_data(
        api.create_time_entry(payload, make_engagement_staff_headers(staff_id))
    )


def request_waiver(
    api, staff_id: str, engagement_id: str, week_start_date: str, extra_hours: float, **overrides: Any
) -> JsonDict:
    """A staff member asks for overtime relief for one of their own weeks."""

    payload = create_workload_waiver_payload(
        staff_id,
        engagement_id,
        week_start_date=week_start_date,
        extra_hours_allowance=extra_hours,
        **overrides,
    )
    return get_success_data(
        api.create_workload_waiver(payload, make_engagement_staff_headers(staff_id))
    )


def approve_waiver(api, waiver_id: str, partner_id: str) -> JsonDict:
    """The engagement partner grants the relief."""

    return get_success_data(
        api.approve_workload_waiver(waiver_id, make_engagement_partner_headers(partner_id))
    )


def create_approved_waiver(
    api,
    staff_id: str,
    engagement_id: str,
    partner_id: str,
    week_start_date: str,
    extra_hours: float,
    **overrides: Any,
) -> JsonDict:
    waiver = request_waiver(
        api, staff_id, engagement_id, week_start_date, extra_hours, **overrides
    )
    approve_waiver(api, waiver["id"], partner_id)
    return waiver


# ---------------------------------------------------------------------------
# Tier 2 -- lifecycle drivers
# ---------------------------------------------------------------------------


def schedule_engagement(api, engagement_id: str) -> JsonDict:
    return get_success_data(
        api.schedule_engagement(engagement_id, scheduling_manager_headers())
    )


def start_fieldwork(api, engagement_id: str) -> JsonDict:
    return get_success_data(
        api.start_fieldwork(engagement_id, scheduling_manager_headers())
    )


def drive_engagement_to_in_fieldwork(api, engagement_id: str) -> JsonDict:
    schedule_engagement(api, engagement_id)
    return start_fieldwork(api, engagement_id)


def confirm_assignment(api, assignment_id: str) -> JsonDict:
    return get_success_data(
        api.confirm_assignment(assignment_id, scheduling_manager_headers())
    )


def start_phase(api, phase_id: str) -> JsonDict:
    return get_success_data(api.start_phase(phase_id, scheduling_manager_headers()))


def activate_assignment(api, assignment_id: str) -> JsonDict:
    return get_success_data(
        api.activate_assignment(assignment_id, scheduling_manager_headers())
    )


def complete_phase(api, phase_id: str) -> JsonDict:
    return get_success_data(api.complete_phase(phase_id, scheduling_manager_headers()))


def drive_assignment_to_active(api, engagement_id: str, phase_id: str, assignment_id: str) -> JsonDict:
    """Schedule, enter fieldwork, confirm, start the phase, then activate."""

    drive_engagement_to_in_fieldwork(api, engagement_id)
    confirm_assignment(api, assignment_id)
    start_phase(api, phase_id)
    return activate_assignment(api, assignment_id)


def report_client_block(api, engagement_id: str, reason_note: str, blocked_until_date: Optional[str] = None) -> JsonDict:
    return get_success_data(
        api.report_client_block(
            engagement_id,
            scheduling_manager_headers(),
            reason_note=reason_note,
            blocked_until_date=blocked_until_date,
        )
    )


def clear_client_block(api, engagement_id: str, partner_id: str) -> JsonDict:
    """Only the engagement's own partner may confirm the client is ready."""

    return get_success_data(
        api.clear_client_block(engagement_id, make_engagement_partner_headers(partner_id))
    )


def deliver_engagement(api, engagement_id: str, partner_id: str) -> JsonDict:
    return get_success_data(
        api.deliver_engagement(engagement_id, make_engagement_partner_headers(partner_id))
    )


def start_review(api, assignment_id: str, reviewer_id: str) -> JsonDict:
    """The nominated review owner opens the review."""

    return get_success_data(
        api.start_review(assignment_id, make_engagement_partner_headers(reviewer_id))
    )


def request_rework(api, assignment_id: str, reviewer_id: str, reason_note: Optional[str] = None) -> JsonDict:
    return get_success_data(
        api.request_rework(
            assignment_id, make_engagement_partner_headers(reviewer_id), reason_note
        )
    )


def accept_review(api, assignment_id: str, reviewer_id: str) -> JsonDict:
    return get_success_data(
        api.accept_review(assignment_id, make_engagement_partner_headers(reviewer_id))
    )


def create_plan(api, engagement_id: str, **overrides: Any) -> JsonDict:
    payload = create_reschedule_plan_payload(engagement_id, **overrides)
    return get_success_data(
        api.create_reschedule_plan(payload, scheduling_manager_headers())
    )


def simulate_plan(api, plan_id: str) -> JsonDict:
    return get_success_data(
        api.simulate_reschedule_plan(plan_id, scheduling_manager_headers())
    )


def apply_plan(api, plan_id: str, expected_engagement_version: Any) -> JsonDict:
    return get_success_data(
        api.apply_reschedule_plan(
            plan_id, scheduling_manager_headers(), expected_engagement_version
        )
    )


def read_engagement(api, engagement_id: str) -> JsonDict:
    return get_success_data(
        api.get_engagement(engagement_id, scheduling_manager_headers())
    )


def read_phase(api, phase_id: str) -> JsonDict:
    return get_success_data(
        api.get_engagement_phase(phase_id, scheduling_manager_headers())
    )


def read_assignment(api, assignment_id: str) -> JsonDict:
    return get_success_data(
        api.get_assignment(assignment_id, scheduling_manager_headers())
    )


def read_staff(api, staff_id: str) -> JsonDict:
    return get_success_data(api.get_staff_member(staff_id, scheduling_manager_headers()))


def read_workload(api, staff_id: str, week_start_date: Optional[str] = None) -> JsonDict:
    return get_success_data(
        api.get_staff_workload(staff_id, scheduling_manager_headers(), week_start_date)
    )


def read_realization(api, engagement_id: str) -> JsonDict:
    return get_success_data(
        api.get_engagement_realization(engagement_id, scheduling_manager_headers())
    )


def read_review_window(api, window_id: str) -> JsonDict:
    return get_success_data(
        api.get_review_capacity_window(window_id, firm_admin_headers())
    )


def read_waiver(api, waiver_id: str) -> JsonDict:
    return get_success_data(
        api.get_workload_waiver(waiver_id, scheduling_manager_headers())
    )


def read_plan(api, plan_id: str) -> JsonDict:
    return get_success_data(
        api.get_reschedule_plan(plan_id, scheduling_manager_headers())
    )


def read_restriction(api, restriction_id: str) -> JsonDict:
    return get_success_data(
        api.get_independence_restriction(restriction_id, independence_officer_headers())
    )


def engagement_version(api, engagement_id: str) -> int:
    return read_engagement(api, engagement_id)["version"]


def phase_version(api, phase_id: str) -> int:
    return read_phase(api, phase_id)["version"]


# ---------------------------------------------------------------------------
# Tier 3 -- the recurring manufacturing-client world
# ---------------------------------------------------------------------------


def manufacturing_world(
    api,
    clock: str = "2026-08-03T09:00:00Z",
    client_name: str = "Meridian Manufacturing",
    partner_name: str = "Pat Rowe",
    senior_name: str = "Sam Oyelaran",
    senior_base_hours: float = 40.00,
    senior_rate: float = 180.00,
    public_interest_entity: bool = False,
) -> Dict[str, JsonDict]:
    """Clock, one manufacturing client, one domestic partner, one senior."""

    set_clock(api, clock)
    client = create_client(
        api, name=client_name, public_interest_entity=public_interest_entity
    )
    partner = create_partner(api, full_name=partner_name)
    senior = create_senior(
        api,
        full_name=senior_name,
        base_weekly_cap_hours=senior_base_hours,
        hourly_bill_rate=senior_rate,
    )
    return {"client": client, "partner": partner, "senior": senior}


def manufacturing_engagement(
    api,
    clock: str = "2026-08-03T09:00:00Z",
    budget_fee_amount: float = 6000.00,
    **world_overrides: Any,
) -> Dict[str, JsonDict]:
    """The manufacturing world plus one audit engagement in SETUP."""

    world = manufacturing_world(api, clock=clock, **world_overrides)
    engagement = create_engagement(
        api,
        world["client"]["id"],
        world["partner"]["id"],
        budget_fee_amount=budget_fee_amount,
    )
    world["engagement"] = engagement
    return world


def manufacturing_fieldwork_phase(
    api,
    clock: str = "2026-08-03T09:00:00Z",
    budget_fee_amount: float = 6000.00,
    expected_hours: float = 45.00,
    window_start_date: str = "2026-08-03",
    window_end_date: str = "2026-08-31",
    required_industry_specialization: Optional[str] = "MANUFACTURING",
    requires_cpa_licensed: Optional[bool] = True,
    phase_type: str = "FIELDWORK",
    required_level: str = "SENIOR",
    **world_overrides: Any,
) -> Dict[str, JsonDict]:
    """The manufacturing engagement plus one phase awaiting staff."""

    world = manufacturing_engagement(
        api, clock=clock, budget_fee_amount=budget_fee_amount, **world_overrides
    )
    phase = create_phase(
        api,
        world["engagement"]["id"],
        phase_type=phase_type,
        expected_hours=expected_hours,
        window_start_date=window_start_date,
        window_end_date=window_end_date,
        required_level=required_level,
        required_industry_specialization=required_industry_specialization,
        requires_cpa_licensed=requires_cpa_licensed,
    )
    world["phase"] = phase
    return world


def manufacturing_booked_phase(
    api,
    allocated_hours: float = 45.00,
    start_date: str = "2026-08-03",
    end_date: str = "2026-08-10",
    **phase_overrides: Any,
) -> Dict[str, JsonDict]:
    """A fieldwork phase carrying one proposed booking for the senior."""

    world = manufacturing_fieldwork_phase(api, **phase_overrides)
    world["assignment"] = create_assignment(
        api,
        world["phase"]["id"],
        world["senior"]["id"],
        start_date=start_date,
        end_date=end_date,
        allocated_hours=allocated_hours,
    )
    return world


# ---------------------------------------------------------------------------
# Tier 4 -- the offshore review world
# ---------------------------------------------------------------------------


def offshore_review_world(
    api,
    clock: str = "2026-08-24T09:00:00Z",
    client_name: str = "Alderwood Industrial",
    reviewer_name: str = "Mira Lindqvist",
    offshore_name: str = "Omar Bhatt",
    offshore_level: str = "STAFF",
    offshore_rate: float = 90.00,
    review_windows: Optional[List[Dict[str, Any]]] = None,
    budget_fee_amount: float = 9000.00,
    phase_type: str = "INTERIM",
    expected_hours: float = 6.00,
    window_start_date: str = "2026-08-24",
    window_end_date: str = "2026-08-31",
    required_level: str = "STAFF",
) -> Dict[str, Any]:
    """A domestic reviewer, an offshore executor and their review windows."""

    set_clock(api, clock)
    client = create_client(api, name=client_name)
    partner = create_partner(api)
    reviewer = create_reviewer(api, full_name=reviewer_name)
    offshore = create_offshore_staff(
        api,
        full_name=offshore_name,
        level=offshore_level,
        hourly_bill_rate=offshore_rate,
    )
    windows: List[JsonDict] = []
    for spec in review_windows or [{"week_start_date": "2026-08-24", "review_capacity_hours": 10.00}]:
        windows.append(
            create_review_window(
                api,
                reviewer["id"],
                spec["week_start_date"],
                spec["review_capacity_hours"],
            )
        )
    engagement = create_engagement(
        api, client["id"], partner["id"], budget_fee_amount=budget_fee_amount
    )
    phase = create_phase(
        api,
        engagement["id"],
        phase_type=phase_type,
        expected_hours=expected_hours,
        window_start_date=window_start_date,
        window_end_date=window_end_date,
        required_level=required_level,
        required_industry_specialization=None,
        requires_cpa_licensed=False,
    )
    return {
        "client": client,
        "partner": partner,
        "reviewer": reviewer,
        "offshore": offshore,
        "review_windows": windows,
        "engagement": engagement,
        "phase": phase,
    }


# ---------------------------------------------------------------------------
# Tier 5 -- workload history builders
# ---------------------------------------------------------------------------


def accumulate_prior_week_actuals(
    api,
    staff_id: str,
    partner_id: str,
    client_id: str,
    week_start_date: str,
    booking_hours: float,
    booking_start: str,
    booking_end: str,
    daily_logs: List[Dict[str, Any]],
    phase_expected_hours: float,
    phase_window_start: str,
    phase_window_end: str,
    engagement_budget: float = 20000.00,
    busy_season_year: int = 2026,
    service_line: str = "AUDIT",
    required_level: str = "SENIOR",
) -> Dict[str, JsonDict]:
    """Drive one booking all the way to ACTIVE and log worked hours against it.

    Used to give a staff member a prior-week actual utilisation figure, which is
    what the weekly cap's tier selection reads.
    """

    engagement = create_engagement(
        api,
        client_id,
        partner_id,
        service_line=service_line,
        busy_season_year=busy_season_year,
        budget_fee_amount=engagement_budget,
    )
    phase = create_phase(
        api,
        engagement["id"],
        expected_hours=phase_expected_hours,
        window_start_date=phase_window_start,
        window_end_date=phase_window_end,
        required_level=required_level,
        required_industry_specialization=None,
        requires_cpa_licensed=False,
    )
    assignment = create_assignment(
        api,
        phase["id"],
        staff_id,
        start_date=booking_start,
        end_date=booking_end,
        allocated_hours=booking_hours,
    )
    drive_assignment_to_active(api, engagement["id"], phase["id"], assignment["id"])
    entries: List[JsonDict] = []
    for log in daily_logs:
        entries.append(
            create_time_entry(
                api,
                assignment["id"],
                staff_id,
                work_date=log["work_date"],
                hours=log["hours"],
                entry_type=log.get("entry_type", "EXECUTION"),
            )
        )
    return {
        "engagement": engagement,
        "phase": phase,
        "assignment": assignment,
        "time_entries": entries,
    }


def build_weekly_bookings(
    api,
    phase_id: str,
    staff_id: str,
    weeks: List[Dict[str, Any]],
) -> List[JsonDict]:
    """Create one booking per described week against the same phase."""

    created: List[JsonDict] = []
    for week in weeks:
        created.append(
            create_assignment(
                api,
                phase_id,
                staff_id,
                start_date=week["start_date"],
                end_date=week["end_date"],
                allocated_hours=week["allocated_hours"],
            )
        )
    return created


__all__ = [
    "set_clock",
    "create_client",
    "create_staff",
    "create_partner",
    "create_senior",
    "create_reviewer",
    "create_offshore_staff",
    "create_engagement",
    "create_phase",
    "create_assignment",
    "create_availability_exception",
    "create_review_window",
    "create_restriction",
    "create_time_entry",
    "request_waiver",
    "approve_waiver",
    "create_approved_waiver",
    "schedule_engagement",
    "start_fieldwork",
    "drive_engagement_to_in_fieldwork",
    "confirm_assignment",
    "start_phase",
    "activate_assignment",
    "complete_phase",
    "drive_assignment_to_active",
    "report_client_block",
    "clear_client_block",
    "deliver_engagement",
    "start_review",
    "request_rework",
    "accept_review",
    "create_plan",
    "simulate_plan",
    "apply_plan",
    "read_engagement",
    "read_phase",
    "read_assignment",
    "read_staff",
    "read_workload",
    "read_realization",
    "read_review_window",
    "read_waiver",
    "read_plan",
    "read_restriction",
    "engagement_version",
    "phase_version",
    "manufacturing_world",
    "manufacturing_engagement",
    "manufacturing_fieldwork_phase",
    "manufacturing_booked_phase",
    "offshore_review_world",
    "accumulate_prior_week_actuals",
    "build_weekly_bookings",
]
