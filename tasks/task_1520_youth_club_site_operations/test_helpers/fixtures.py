"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) so setup failures produce clear
"Setup step failed" errors instead of confusing assertion failures.

Identity threading: SiteDirector/FrontlineStaff are entity-backed roles (PRD
2.1), so every ownership/role-gated call below builds headers from the actual
Staff row's id via make_site_director_headers / make_frontline_staff_headers.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK, FAR_FUTURE_EXPIRY
from .factories import (
    create_adjudicate_payload,
    create_area_payload,
    create_attendance_payload,
    create_award_payload,
    create_claim_payload,
    create_club_day_payload,
    create_credential_payload,
    create_decide_payload,
    create_fund_payload,
    create_guardian_payload,
    create_incident_payload,
    create_meal_counts_payload,
    create_member_payload,
    create_report_payload,
    create_ride_payload,
    create_rotation_payload,
    create_route_payload,
    create_sign_out_payload,
    create_site_payload,
    create_staff_payload,
)
from .test_users import (
    TEST_USERS,
    make_site_director_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]


# --- Tier 0: clock and site scaffolding --------------------------------------


def set_logical_clock(to_iso8601: str) -> dict:
    """Move the logical clock (PRD 2.4). Returns {current_utc: ...}."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def create_site(clock: str = None, **overrides) -> dict:
    """Create a site (optionally moving the clock first). Returns the site."""
    if clock is not None:
        set_logical_clock(clock)
    return get_success_data(api_client.create_site(create_site_payload(**overrides), ADMIN))


def create_credentialed_staff(site_id: str, full_name: str = "Dir One",
                              position: str = "DIRECTOR",
                              expires_at: str = FAR_FUTURE_EXPIRY) -> dict:
    """Hire a staff member and post both credentials so the system promotes
    them to ACTIVE (PRD 3.1). Returns the staff row."""
    staff = get_success_data(
        api_client.create_staff(create_staff_payload(site_id, full_name, position), ADMIN)
    )
    api_client.post_staff_credential(
        staff["id"], create_credential_payload("BACKGROUND_CHECK", expires_at), ADMIN
    )
    staff = get_success_data(
        api_client.post_staff_credential(
            staff["id"], create_credential_payload("TRAINING", expires_at), ADMIN
        )
    )
    return staff


def setup_site_with_director(clock: str = DEFAULT_CLOCK, **site_overrides):
    """Create a site plus an ACTIVE DIRECTOR staff member. Returns (site, director)."""
    site = create_site(clock=clock, **site_overrides)
    director = create_credentialed_staff(site["id"], "Dir One", "DIRECTOR")
    return site, director


def setup_site_with_director_and_frontline(clock: str = DEFAULT_CLOCK, **site_overrides):
    """Site + ACTIVE director + ACTIVE frontline staffer. Returns (site, dir, flo)."""
    site, director = setup_site_with_director(clock=clock, **site_overrides)
    frontline = create_credentialed_staff(site["id"], "Flo One", "FRONTLINE")
    return site, director, frontline


def director_headers(director: dict) -> dict:
    return make_site_director_headers(director["id"])


# --- Tier 1: members ----------------------------------------------------------


def apply_for_membership(site_id: str, director_id: str, **overrides) -> dict:
    """Submit a membership application (status APPLIED). Returns the member."""
    return get_success_data(
        api_client.create_member(
            create_member_payload(site_id, **overrides),
            make_site_director_headers(director_id),
        )
    )


def decide_member(member_id: str, director_id: str, decision: str = "APPROVE") -> dict:
    return get_success_data(
        api_client.decide_member(
            member_id, create_decide_payload(decision),
            make_site_director_headers(director_id),
        )
    )


def create_active_member(site_id: str, director_id: str, **overrides) -> dict:
    """Apply + approve. Returns the ACTIVE member."""
    member = apply_for_membership(site_id, director_id, **overrides)
    return decide_member(member["id"], director_id, "APPROVE")


def get_member(member_id: str) -> dict:
    return get_success_data(api_client.get_member(member_id, ADMIN))


def create_guardian(member_id: str, director_id: str, full_name: str = "Jane Doe",
                    relation: str = "mother", **overrides) -> dict:
    return get_success_data(
        api_client.create_guardian(
            create_guardian_payload(member_id, full_name, relation, **overrides),
            make_site_director_headers(director_id),
        )
    )


# --- Tier 2: club days and attendance -----------------------------------------


def open_club_day(site_id: str, director_id: str, date: str,
                  clock_time: str = "09:00:00") -> dict:
    """Move the clock to `date` and open the club day. Returns the OPEN day."""
    set_logical_clock(f"{date}T{clock_time}Z")
    return get_success_data(
        api_client.create_club_day(
            create_club_day_payload(site_id, date),
            make_site_director_headers(director_id),
        )
    )


def get_club_day(day_id: str) -> dict:
    return get_success_data(api_client.get_club_day(day_id, ADMIN))


def sign_in_member(club_day_id: str, member_id: str, director_id: str) -> dict:
    return get_success_data(
        api_client.create_attendance_record(
            create_attendance_payload(club_day_id, member_id),
            make_site_director_headers(director_id),
        )
    )


def walker_sign_out(attendance_id: str, director_id: str) -> dict:
    return get_success_data(
        api_client.sign_out_attendance(
            attendance_id, create_sign_out_payload("WALKER"),
            make_site_director_headers(director_id),
        )
    )


def set_meal_counts(day_id: str, director_id: str, meal_type: str = "BREAKFAST",
                    free_count: int = 0, reduced_count: int = 0,
                    paid_count: int = 0) -> dict:
    return get_success_data(
        api_client.upsert_meal_counts(
            day_id,
            create_meal_counts_payload(meal_type, free_count, reduced_count, paid_count),
            make_site_director_headers(director_id),
        )
    )


def close_day(day_id: str, director_id: str) -> dict:
    return get_success_data(
        api_client.close_club_day(day_id, make_site_director_headers(director_id))
    )


def reconcile_day(day_id: str, director_id: str) -> dict:
    return get_success_data(
        api_client.reconcile_club_day(day_id, make_site_director_headers(director_id))
    )


def run_day(site_id: str, director_id: str, date: str, member_ids=(),
            meal_counts=None, walker_sign_out: bool = False,
            close: bool = False, reconcile: bool = False,
            clock_time: str = "09:00:00") -> dict:
    """Open `date`, sign in each member, optionally upsert one meal-count row,
    optionally WALKER-sign-out everyone, optionally close and reconcile.
    Returns {"day": day, "attendance": [AttendanceRecord, ...]}."""
    day = open_club_day(site_id, director_id, date, clock_time=clock_time)
    records = [sign_in_member(day["id"], mid, director_id) for mid in member_ids]
    if meal_counts is not None:
        day = set_meal_counts(day["id"], director_id, **meal_counts)
    if walker_sign_out:
        # The `walker_sign_out` parameter shadows the module-level helper above;
        # reference it explicitly.
        sign_out_fn = globals()["walker_sign_out"]
        records = [sign_out_fn(r["id"], director_id) for r in records]
    if close:
        day = close_day(day["id"], director_id)
    if reconcile:
        day = reconcile_day(day["id"], director_id)
    return {"day": day, "attendance": records}


def accrue_friday(site_id: str, director_id: str, friday_date: str) -> dict:
    """Open and immediately close a club day whose date falls on the site's
    fee-accrual weekday, running the weekly fee accrual (PRD 3.9)."""
    day = open_club_day(site_id, director_id, friday_date, clock_time="16:00:00")
    return close_day(day["id"], director_id)


# --- Tier 2: program areas and rotation ----------------------------------------


def create_area(site_id: str, name: str = "Gym", capacity: int = 30,
                **overrides) -> dict:
    return get_success_data(
        api_client.create_program_area(
            create_area_payload(site_id, name, capacity, **overrides), ADMIN
        )
    )


def schedule_staff_assignment(day_id: str, area_id: str, staff_id: str,
                              director_id: str, block: str = "BLOCK_A") -> dict:
    return get_success_data(
        api_client.create_rotation_assignment(
            create_rotation_payload(day_id, area_id, block, "STAFF", staff_id=staff_id),
            make_site_director_headers(director_id),
        )
    )


def schedule_youth_assignment(day_id: str, area_id: str, member_id: str,
                              director_id: str, block: str = "BLOCK_A") -> dict:
    return get_success_data(
        api_client.create_rotation_assignment(
            create_rotation_payload(day_id, area_id, block, "YOUTH", member_id=member_id),
            make_site_director_headers(director_id),
        )
    )


def check_in_assignment(assignment_id: str, director_id: str) -> dict:
    return get_success_data(
        api_client.check_in_rotation_assignment(
            assignment_id, make_site_director_headers(director_id)
        )
    )


# --- Tier 2: transport ----------------------------------------------------------


def create_route(site_id: str, route_name: str = "Route 1",
                 school_name: str = "Lincoln", seat_capacity: int = 5) -> dict:
    return get_success_data(
        api_client.create_transport_route(
            create_route_payload(site_id, route_name, school_name, seat_capacity), ADMIN
        )
    )


def assign_ride(route_id: str, member_id: str, director_id: str,
                effective_start_date: str, effective_end_date=None) -> dict:
    return get_success_data(
        api_client.create_ride_assignment(
            create_ride_payload(route_id, member_id, effective_start_date,
                                effective_end_date),
            make_site_director_headers(director_id),
        )
    )


# --- Tier 2: scholarship --------------------------------------------------------


def create_fund(site_id: str, budget_cents: int = 10_000, name: str = "Fund S") -> dict:
    return get_success_data(
        api_client.create_scholarship_fund(
            create_fund_payload(site_id, name, budget_cents), ADMIN
        )
    )


def get_fund(fund_id: str) -> dict:
    return get_success_data(api_client.get_scholarship_fund(fund_id, ADMIN))


def create_award(fund_id: str, member_id: str, director_id: str,
                 discount_pct: float = 0.50, weekly_cap_cents: int = 500,
                 annual_cap_cents: int = 1000) -> dict:
    return get_success_data(
        api_client.create_scholarship_award(
            create_award_payload(fund_id, member_id, discount_pct,
                                 weekly_cap_cents, annual_cap_cents),
            make_site_director_headers(director_id),
        )
    )


def activate_award(award_id: str, director_id: str, expected_fund_version: int) -> dict:
    return get_success_data(
        api_client.activate_scholarship_award(
            award_id, {"expected_fund_version": expected_fund_version},
            make_site_director_headers(director_id),
        )
    )


def setup_activated_award(site_id: str, director_id: str, member_id: str,
                          budget_cents: int, discount_pct: float,
                          weekly_cap_cents: int, annual_cap_cents: int):
    """Fund + PENDING award + activation. Returns (fund, award)."""
    fund = create_fund(site_id, budget_cents)
    award = create_award(fund["id"], member_id, director_id,
                         discount_pct, weekly_cap_cents, annual_cap_cents)
    award = activate_award(award["id"], director_id, fund["version"])
    return fund, award


# --- Tier 2: behavior incidents -------------------------------------------------


def report_incident(member_id: str, director_id: str, incident_date: str,
                    category: str, description=None) -> dict:
    return get_success_data(
        api_client.create_behavior_incident(
            create_incident_payload(member_id, incident_date, category, description),
            make_site_director_headers(director_id),
        )
    )


def adjudicate_incident(incident_id: str, director_id: str, outcome: str = "SUSTAINED",
                        suspension_days=None, suspension_start_date=None) -> dict:
    return get_success_data(
        api_client.adjudicate_incident(
            incident_id,
            create_adjudicate_payload(outcome, suspension_days, suspension_start_date),
            make_site_director_headers(director_id),
        )
    )


def suspend_member_now(member_id: str, director_id: str, date: str,
                       suspension_days: int = 1, category: str = "LEVEL_1") -> dict:
    """Report + adjudicate an incident with a suspension starting `date`.
    When `date` is today or earlier the member flips to SUSPENDED on the spot
    (PRD 3.8). Returns the incident."""
    incident = report_incident(member_id, director_id, date, category)
    return adjudicate_incident(
        incident["id"], director_id, "SUSTAINED",
        suspension_days=suspension_days, suspension_start_date=date,
    )


# --- Tier 3: meal claims and funder reports -------------------------------------


def create_claim(site_id: str, director_id: str, claim_month: str) -> dict:
    return get_success_data(
        api_client.create_meal_claim(
            create_claim_payload(site_id, claim_month),
            make_site_director_headers(director_id),
        )
    )


def submit_claim(claim_id: str, director_id: str) -> dict:
    return get_success_data(
        api_client.submit_meal_claim(claim_id, make_site_director_headers(director_id))
    )


def setup_submitted_claim(month: str = "2026-08", day_date: str = "2026-08-03",
                          free_count: int = 1):
    """Site + director + one FREE walker member; a fully reconciled club day with
    one BREAKFAST FREE row per member; a meal claim created and SUBMITTED.
    Returns a context dict."""
    site, director = setup_site_with_director(clock=DEFAULT_CLOCK)
    members = [
        create_active_member(
            site["id"], director["id"], legal_name=f"Kid {i}", walker_ok=True
        )
        for i in range(1, free_count + 1)
    ]
    run_day(
        site["id"], director["id"], day_date,
        member_ids=[m["id"] for m in members],
        meal_counts={"meal_type": "BREAKFAST", "free_count": free_count,
                     "reduced_count": 0, "paid_count": 0},
        walker_sign_out=True, close=True, reconcile=True,
    )
    member = members[0]
    claim = create_claim(site["id"], director["id"], month)
    claim = submit_claim(claim["id"], director["id"])
    return {"site": site, "director": director, "member": member, "claim": claim}


def create_report(site_id: str, director_id: str, report_month: str,
                  funder_type: str) -> dict:
    return get_success_data(
        api_client.create_funder_report(
            create_report_payload(site_id, report_month, funder_type),
            make_site_director_headers(director_id),
        )
    )
