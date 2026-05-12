"""Composite setup helpers for multi-step preconditions.

Walking the PRD's lifecycle from a freshly registered Volunteer all the
way through identity verification, skill declaration & approval,
Activity authoring & approval, the time-gated PUBLISHED -> RECRUITING ->
RUNNING -> COMPLETED transitions, application approval, check-in,
check-out, and the cascade into Volunteer totals takes 10+ API calls.
This module captures the common multi-call sequences once.

Identity threading (PRD §2.1): when a fixture creates a Volunteer, ANY
downstream call where the acting role is `Volunteer` MUST use
make_volunteer_headers(volunteer["id"]). When a fixture promotes that
volunteer to organizer-of-an-activity, downstream organizer-side calls
MUST use make_organizer_headers(volunteer["id"]). Falling back to the
shared TEST_USERS constants for these roles would make every ownership
check fail and cascade "Setup failed" into dozens of tests.

Setup calls use get_success_data (lenient) so failed pre-conditions
surface as 'Setup failed' messages rather than confusing assertion
mismatches.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_BASELINE_ISO
from .factories import (
    apply_to_activity_payload,
    check_in_payload,
    create_activity_payload,
    create_certificate_template_payload,
    create_point_mall_item_payload,
    create_redemption_order_payload,
    create_skill_payload,
    create_volunteer_payload,
    declare_volunteer_skill_payload,
    define_activity_role_payload,
    file_hour_adjustment_payload,
    issue_certificate_payload,
    leave_payload,
    manual_correction_payload,
    resubmit_volunteer_skill_payload,
    unique_id_number_hash,
    unique_skill_code,
    unique_volunteer_full_name,
    unique_template_code,
    unique_sku,
)
from .test_users import (
    TEST_USERS,
    make_organizer_headers,
    make_skilladmin_headers,
    make_volunteer_headers,
)


# ===========================================================================
# Time helpers (PRD §2.11 logical clock; PRD §2.5 timestamp format)
# ===========================================================================
def iso_z(dt: datetime) -> str:
    """Render a datetime as ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = int(dt.microsecond / 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{millis:03d}Z"


def parse_iso(s: str) -> datetime:
    s2 = s.replace("Z", "+00:00")
    return datetime.fromisoformat(s2)


def add_seconds(s: str, n: int) -> str:
    return iso_z(parse_iso(s) + timedelta(seconds=n))


def add_minutes(s: str, n: float) -> str:
    return iso_z(parse_iso(s) + timedelta(minutes=n))


def add_hours(s: str, n: float) -> str:
    return iso_z(parse_iso(s) + timedelta(hours=n))


def add_days(s: str, n: int) -> str:
    return iso_z(parse_iso(s) + timedelta(days=n))


# ===========================================================================
# Clock control (PRD §2.11)
# ===========================================================================
def reset_clock_to_baseline() -> Dict[str, Any]:
    """Try to anchor the server clock at CLOCK_BASELINE_ISO.

    The PRD §2.11 contract exposes only forward advancement; if the
    server happens to already be past the baseline, this call may itself
    fail. That is acceptable — fixtures that need fresh time invariants
    should pass an absolute target_time well into the future.
    """
    return get_success_data(
        api_client.advance_clock(CLOCK_BASELINE_ISO, make_skilladmin_headers())
    )


def advance_clock(target_time: str) -> Dict[str, Any]:
    """POST /_clock/advance with SkillAdmin headers (PRD §2.11)."""
    return get_success_data(
        api_client.advance_clock(target_time, make_skilladmin_headers())
    )


def get_clock() -> Dict[str, Any]:
    """GET /_clock with SkillAdmin headers (PRD §2.11)."""
    return get_success_data(api_client.get_clock(make_skilladmin_headers()))


# ===========================================================================
# Tier 1: Volunteer creation and identity progression (PRD §3.1)
# ===========================================================================
def create_volunteer(
    *,
    full_name: Optional[str] = None,
    home_lat: float = 30.000000,
    home_lng: float = 120.000000,
    **overrides: Any,
) -> Dict[str, Any]:
    """Register a fresh Volunteer (status PENDING)."""
    payload = create_volunteer_payload(
        full_name=full_name,
        home_lat=home_lat,
        home_lng=home_lng,
        **overrides,
    )
    return get_success_data(
        api_client.create_volunteer(payload, make_skilladmin_headers())
    )


def verify_identity(volunteer_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.verify_identity(volunteer_id, make_skilladmin_headers())
    )


def reject_identity(volunteer_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.reject_identity(volunteer_id, make_skilladmin_headers())
    )


def create_verified_volunteer(
    *,
    home_lat: float = 30.000000,
    home_lng: float = 120.000000,
    **overrides: Any,
) -> Dict[str, Any]:
    """Convenience: create + identity:verify, return the verified row."""
    v = create_volunteer(home_lat=home_lat, home_lng=home_lng, **overrides)
    return verify_identity(v["id"])


def create_volunteer_with_clearance(
    *,
    home_lat: float = 30.000000,
    home_lng: float = 120.000000,
    **overrides: Any,
) -> Dict[str, Any]:
    """Volunteer in identity=VERIFIED + background_check_status=CLEARED.

    Required when the Activity has requires_sensitive_clearance=true
    (PRD §3.4 ERR_BACKGROUND_CHECK_REQUIRED).
    """
    v = create_verified_volunteer(home_lat=home_lat, home_lng=home_lng, **overrides)
    headers = make_volunteer_headers(v["id"])
    get_success_data(api_client.request_background_check(v["id"], headers))
    cleared = get_success_data(
        api_client.clear_background_check(v["id"], make_skilladmin_headers())
    )
    return cleared


# ===========================================================================
# Tier 1b: Skill catalog + VolunteerSkill (PRD §3.2)
# ===========================================================================
def create_skill(
    *,
    code: Optional[str] = None,
    requires_certificate: bool = False,
    sensitivity_level: str = "STANDARD",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = create_skill_payload(
        code=code,
        requires_certificate=requires_certificate,
        sensitivity_level=sensitivity_level,
        **overrides,
    )
    return get_success_data(
        api_client.create_skill(payload, make_skilladmin_headers())
    )


def declare_and_approve_skill(
    *,
    volunteer: Dict[str, Any],
    skill: Dict[str, Any],
    certificate_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Walk VolunteerSkill SELF_DECLARED -> UNDER_REVIEW -> APPROVED.

    PRD §3.2 mandates certificate_url is non-null at submission when
    Skill.requires_certificate is true. Defaults to a placeholder URL
    when needed.
    """
    if skill.get("requires_certificate") and certificate_url is None:
        certificate_url = "https://example.test/cert.pdf"

    headers = make_volunteer_headers(volunteer["id"])
    declared = get_success_data(
        api_client.declare_skill(
            declare_volunteer_skill_payload(
                skill_id=skill["id"], certificate_url=certificate_url
            ),
            headers,
        )
    )
    submitted = get_success_data(
        api_client.submit_volunteer_skill(declared["id"], headers)
    )
    approved = get_success_data(
        api_client.approve_volunteer_skill(submitted["id"], make_skilladmin_headers())
    )
    return approved


def equip_volunteer_with_skills(
    volunteer: Dict[str, Any],
    skills: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """For each skill in skills, declare + submit + approve for the volunteer."""
    out = []
    for s in skills:
        out.append(declare_and_approve_skill(volunteer=volunteer, skill=s))
    return out


# ===========================================================================
# Tier 1c: Activity authoring + state progression (PRD §3.3)
# ===========================================================================
def make_activity_times(
    *,
    base_iso: Optional[str] = None,
    recruit_open_offset_hours: float = 24,
    recruit_close_offset_hours: float = 24 * 14,
    start_offset_hours: float = 24 * 21,
    duration_hours: float = 2,
) -> Dict[str, str]:
    """Build a coherent recruit/start/end quadruple anchored on base_iso.

    When base_iso is None (the default), the times are anchored on the
    SERVER'S CURRENT logical clock at the moment the helper is called.
    Because the logical clock is global state shared across tests in the
    same Docker container session, anchoring on the static
    CLOCK_BASELINE_ISO would silently leave activities marooned in
    PUBLISHED whenever a previous test had advanced the clock past the
    intended recruit_open_at — every downstream apply/approve/check-in
    would then trip ERR_RECRUITMENT_CLOSED.
    """
    if base_iso is None:
        try:
            clock_data = get_clock()
            base_iso = clock_data.get("now") or clock_data.get("current_time") \
                or clock_data.get("clock") or clock_data.get("server_time") \
                or CLOCK_BASELINE_ISO
        except Exception:
            base_iso = CLOCK_BASELINE_ISO
    recruit_open = add_hours(base_iso, recruit_open_offset_hours)
    recruit_close = add_hours(base_iso, recruit_close_offset_hours)
    start = add_hours(base_iso, start_offset_hours)
    end = add_hours(start, duration_hours)
    return {
        "recruit_open_at": recruit_open,
        "recruit_close_at": recruit_close,
        "start_at": start,
        "end_at": end,
    }


def create_draft_activity(
    *,
    organizer: Dict[str, Any],
    location_lat: float = 30.000000,
    location_lng: float = 120.000000,
    required_skill_codes: Optional[List[str]] = None,
    position_quota: int = 5,
    difficulty: str = "MEDIUM",
    hour_rule_type: str = "ACTUAL_DURATION",
    fixed_hour_value: Optional[float] = None,
    times: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Create an Activity in DRAFT with the given organizer.

    Always uses make_organizer_headers(organizer["id"]) so that PRD §2.1
    Activity.organizer_id == X-User-ID enforcement holds for downstream
    /submit, /approve-of-Application, etc.
    """
    times = times if times is not None else make_activity_times()
    payload = create_activity_payload(
        location_lat=location_lat,
        location_lng=location_lng,
        required_skill_codes=required_skill_codes if required_skill_codes is not None else [],
        position_quota=position_quota,
        difficulty=difficulty,
        hour_rule_type=hour_rule_type,
        fixed_hour_value=fixed_hour_value,
        **times,
        **overrides,
    )
    return get_success_data(
        api_client.create_activity(payload, make_organizer_headers(organizer["id"]))
    )


def submit_activity(activity: Dict[str, Any], organizer: Dict[str, Any]) -> Dict[str, Any]:
    return get_success_data(
        api_client.submit_activity(
            activity["id"], make_organizer_headers(organizer["id"])
        )
    )


def approve_activity(activity_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.approve_activity(activity_id, make_skilladmin_headers())
    )


def reject_activity(activity_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.reject_activity(activity_id, make_skilladmin_headers())
    )


def define_activity_role(
    activity: Dict[str, Any],
    organizer: Dict[str, Any],
    *,
    role_label: str,
    coefficient: Optional[float] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.define_activity_role(
            activity["id"],
            define_activity_role_payload(role_label=role_label, coefficient=coefficient),
            make_organizer_headers(organizer["id"]),
        )
    )


def publish_activity(
    *,
    organizer: Dict[str, Any],
    times: Optional[Dict[str, str]] = None,
    required_skill_codes: Optional[List[str]] = None,
    location_lat: float = 30.000000,
    location_lng: float = 120.000000,
    position_quota: int = 5,
    difficulty: str = "MEDIUM",
    hour_rule_type: str = "ACTUAL_DURATION",
    fixed_hour_value: Optional[float] = None,
    role_labels: Optional[List[str]] = None,
    role_coefficients: Optional[Dict[str, float]] = None,
    **overrides: Any,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Create draft Activity -> define roles -> submit -> approve.

    Returns (activity in PUBLISHED, list of ActivityRoles created).

    Roles are defined on the DRAFT before submission. PRD §3.3 says
    "Calls to define ActivityRole rows on a draft activity supply ..."
    — so role definition only requires the activity to exist in DRAFT.
    """
    activity = create_draft_activity(
        organizer=organizer,
        location_lat=location_lat,
        location_lng=location_lng,
        required_skill_codes=required_skill_codes,
        position_quota=position_quota,
        difficulty=difficulty,
        hour_rule_type=hour_rule_type,
        fixed_hour_value=fixed_hour_value,
        times=times,
        **overrides,
    )

    roles: List[Dict[str, Any]] = []
    role_coefficients = role_coefficients or {}
    for label in role_labels or []:
        roles.append(
            define_activity_role(
                activity, organizer,
                role_label=label, coefficient=role_coefficients.get(label),
            )
        )

    submit_activity(activity, organizer)
    published = approve_activity(activity["id"])
    return published, roles


# ---------------------------------------------------------------------------
# Activity time-gated transitions (PRD §3.3 / §2.11)
# ---------------------------------------------------------------------------
def advance_to_recruiting(activity: Dict[str, Any]) -> Dict[str, Any]:
    """Advance clock to recruit_open_at to drive PUBLISHED -> RECRUITING."""
    advance_clock(activity["recruit_open_at"])
    return get_success_data(
        api_client.get_activity(activity["id"], make_skilladmin_headers())
    )


def advance_to_running(activity: Dict[str, Any]) -> Dict[str, Any]:
    """Advance clock to start_at to drive RECRUITING -> RUNNING.

    PRD §3.3 cascade: any APPLIED Application is auto-rejected
    (status -> REJECTED).
    """
    advance_clock(activity["start_at"])
    return get_success_data(
        api_client.get_activity(activity["id"], make_skilladmin_headers())
    )


def advance_to_completed(activity: Dict[str, Any]) -> Dict[str, Any]:
    """Advance clock to end_at to drive RUNNING -> COMPLETED.

    PRD §3.3 cascade: every Application still in CHECKED_IN with no
    check_out_at gets check_out_at = end_at and is COMPLETED with full
    hour/point computation; every Application still in APPROVED with no
    check_in_at becomes NO_SHOW.
    """
    advance_clock(activity["end_at"])
    return get_success_data(
        api_client.get_activity(activity["id"], make_skilladmin_headers())
    )


# ===========================================================================
# Tier 2: Application lifecycle (PRD §3.4 / §3.5)
# ===========================================================================
def apply_to_activity(
    *,
    volunteer: Dict[str, Any],
    activity: Dict[str, Any],
    activity_role_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Volunteer applies to a RECRUITING Activity. Returns Application APPLIED."""
    return get_success_data(
        api_client.apply_to_activity(
            apply_to_activity_payload(
                activity_id=activity["id"], activity_role_id=activity_role_id
            ),
            make_volunteer_headers(volunteer["id"]),
        )
    )


def approve_application(
    *,
    application: Dict[str, Any],
    organizer: Dict[str, Any],
) -> Dict[str, Any]:
    """Organizer approves an APPLIED Application -> APPROVED."""
    return get_success_data(
        api_client.approve_application(
            application["id"], make_organizer_headers(organizer["id"])
        )
    )


def reject_application(
    *,
    application: Dict[str, Any],
    organizer: Dict[str, Any],
) -> Dict[str, Any]:
    return get_success_data(
        api_client.reject_application(
            application["id"], make_organizer_headers(organizer["id"])
        )
    )


def withdraw_application(
    *,
    application: Dict[str, Any],
    volunteer: Dict[str, Any],
) -> Dict[str, Any]:
    return get_success_data(
        api_client.withdraw_application(
            application["id"], make_volunteer_headers(volunteer["id"])
        )
    )


def check_in_via_site_code(
    *,
    application: Dict[str, Any],
    volunteer: Dict[str, Any],
    activity: Dict[str, Any],
) -> Dict[str, Any]:
    """Check in by submitting Activity.site_code (PRD §3.5).

    Reads the freshly-fetched Activity to pick up site_code that was
    minted on /approve. Activity must be RUNNING for the call to succeed.
    """
    fresh = get_success_data(
        api_client.get_activity(activity["id"], make_skilladmin_headers())
    )
    code = fresh.get("site_code")
    return get_success_data(
        api_client.check_in(
            application["id"],
            check_in_payload(site_code=code),
            make_volunteer_headers(volunteer["id"]),
        )
    )


def check_in_via_gps(
    *,
    application: Dict[str, Any],
    volunteer: Dict[str, Any],
    activity: Dict[str, Any],
) -> Dict[str, Any]:
    """Check in by GPS exactly at the activity location (well within 0.50 km)."""
    return get_success_data(
        api_client.check_in(
            application["id"],
            check_in_payload(
                check_in_lat=activity["location_lat"],
                check_in_lng=activity["location_lng"],
            ),
            make_volunteer_headers(volunteer["id"]),
        )
    )


def request_leave(
    *,
    application: Dict[str, Any],
    volunteer: Dict[str, Any],
    leave_reason: str = "Family emergency requiring brief absence.",
) -> Dict[str, Any]:
    return get_success_data(
        api_client.request_leave(
            application["id"],
            leave_payload(leave_reason=leave_reason),
            make_volunteer_headers(volunteer["id"]),
        )
    )


def check_out(
    *,
    application: Dict[str, Any],
    volunteer: Dict[str, Any],
) -> Dict[str, Any]:
    return get_success_data(
        api_client.check_out(
            application["id"], make_volunteer_headers(volunteer["id"])
        )
    )


def manual_correction(
    *,
    application: Dict[str, Any],
    organizer: Dict[str, Any],
    **fields: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.manual_correction(
            application["id"],
            manual_correction_payload(**fields),
            make_organizer_headers(organizer["id"]),
        )
    )


# ===========================================================================
# Tier 3: Composite scenarios — recurring multi-call setups
# ===========================================================================
def setup_organizer() -> Dict[str, Any]:
    """A verified Volunteer who will act as Organizer on activities they create."""
    return create_verified_volunteer(home_lat=30.000000, home_lng=120.000000)


def setup_recruiting_activity(
    *,
    organizer: Optional[Dict[str, Any]] = None,
    required_skill_codes: Optional[List[str]] = None,
    position_quota: int = 5,
    difficulty: str = "MEDIUM",
    hour_rule_type: str = "ACTUAL_DURATION",
    fixed_hour_value: Optional[float] = None,
    role_labels: Optional[List[str]] = None,
    role_coefficients: Optional[Dict[str, float]] = None,
    times: Optional[Dict[str, str]] = None,
    location_lat: float = 30.000000,
    location_lng: float = 120.000000,
) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    """Create organizer (if needed) -> publish Activity -> advance clock to
    recruit_open_at. Returns (organizer, activity_in_RECRUITING, roles).
    """
    if organizer is None:
        organizer = setup_organizer()
    activity, roles = publish_activity(
        organizer=organizer,
        times=times,
        required_skill_codes=required_skill_codes,
        location_lat=location_lat,
        location_lng=location_lng,
        position_quota=position_quota,
        difficulty=difficulty,
        hour_rule_type=hour_rule_type,
        fixed_hour_value=fixed_hour_value,
        role_labels=role_labels,
        role_coefficients=role_coefficients,
    )
    activity = advance_to_recruiting(activity)
    return organizer, activity, roles


def setup_running_activity_with_approved_volunteer(
    *,
    organizer: Optional[Dict[str, Any]] = None,
    required_skills: Optional[List[Dict[str, Any]]] = None,
    difficulty: str = "MEDIUM",
    hour_rule_type: str = "ACTUAL_DURATION",
    fixed_hour_value: Optional[float] = None,
    role_label: Optional[str] = None,
    role_coefficient: Optional[float] = None,
    position_quota: int = 5,
    times: Optional[Dict[str, str]] = None,
    location_lat: float = 30.000000,
    location_lng: float = 120.000000,
    volunteer_home_lat: float = 30.000000,
    volunteer_home_lng: float = 120.000000,
    with_clearance: bool = False,
) -> Dict[str, Any]:
    """Compose: organizer -> Activity PUBLISHED -> RECRUITING -> APPROVED
    Application -> RUNNING. Returns dict with all entities.

    Returns:
      {
        organizer, activity, roles,          # Activity now in RUNNING
        volunteer, application,              # Application in APPROVED
        skills,                              # Approved Skills the volunteer holds
      }
    """
    required_skills = required_skills or []
    required_skill_codes = [s["code"] for s in required_skills]

    role_labels = [role_label] if role_label else []
    role_coefficients = (
        {role_label: role_coefficient} if role_label and role_coefficient is not None else None
    )

    organizer, activity, roles = setup_recruiting_activity(
        organizer=organizer,
        required_skill_codes=required_skill_codes,
        position_quota=position_quota,
        difficulty=difficulty,
        hour_rule_type=hour_rule_type,
        fixed_hour_value=fixed_hour_value,
        role_labels=role_labels,
        role_coefficients=role_coefficients,
        times=times,
        location_lat=location_lat,
        location_lng=location_lng,
    )

    if with_clearance:
        volunteer = create_volunteer_with_clearance(
            home_lat=volunteer_home_lat, home_lng=volunteer_home_lng
        )
    else:
        volunteer = create_verified_volunteer(
            home_lat=volunteer_home_lat, home_lng=volunteer_home_lng
        )

    if required_skills:
        equip_volunteer_with_skills(volunteer, required_skills)

    role_id = roles[0]["id"] if roles else None
    application = apply_to_activity(
        volunteer=volunteer, activity=activity, activity_role_id=role_id
    )
    application = approve_application(application=application, organizer=organizer)

    activity = advance_to_running(activity)

    return {
        "organizer": organizer,
        "activity": activity,
        "roles": roles,
        "volunteer": volunteer,
        "application": application,
        "skills": required_skills,
    }


def setup_completed_application(
    *,
    difficulty: str = "MEDIUM",
    hour_rule_type: str = "ACTUAL_DURATION",
    fixed_hour_value: Optional[float] = None,
    role_label: Optional[str] = "LEAD",
    role_coefficient: Optional[float] = None,
    duration_hours: int = 2,
    check_out_offset_minutes: Optional[float] = None,
    times: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """End-to-end: produce a Volunteer with one COMPLETED Application.

    The volunteer applies, is approved, checks in at start_at, and
    checks out at start_at + duration_hours (default 2 hours, well
    within the activity window so early_departure_marker is false).
    Returns dict with all entities including the COMPLETED Application
    and the up-to-date Volunteer.

    For PRD §3.6 ACTUAL_DURATION + MEDIUM + LEAD with 2.00 hours:
      adjusted_hours == 2.00, points_awarded == floor(20.00*1.50*1.20) = 36.

    Set check_out_offset_minutes to override the 2-hour duration with a
    finer-grained offset (e.g., 90 to force early-departure marker).
    """
    times = times if times is not None else make_activity_times(duration_hours=duration_hours)

    setup = setup_running_activity_with_approved_volunteer(
        difficulty=difficulty,
        hour_rule_type=hour_rule_type,
        fixed_hour_value=fixed_hour_value,
        role_label=role_label,
        role_coefficient=role_coefficient,
        times=times,
    )

    activity = setup["activity"]
    volunteer = setup["volunteer"]
    application = setup["application"]

    # Clock is currently at start_at after advance_to_running. Check in NOW.
    application = check_in_via_site_code(
        application=application, volunteer=volunteer, activity=activity
    )

    # Advance clock to the desired check-out offset.
    # NOTE: if we advance to exactly Activity.end_at, the impl's clock-sweep
    # auto-cascades RUNNING -> COMPLETED, which auto-completes the CHECKED_IN
    # Application BEFORE we issue the manual /check-out call. To preserve the
    # "volunteer-initiated check-out" path, we step the clock to one second
    # short of end_at when the caller wants a "full duration" checkout. The
    # 1-second nudge does not perturb the credited-hours calculation at PRD
    # §2.5 two-decimal precision (1s = 0.000278h rounds to 0.00).
    if check_out_offset_minutes is None:
        check_out_at = add_seconds(activity["end_at"], -1)
    else:
        check_out_at = add_minutes(activity["start_at"], check_out_offset_minutes)
    advance_clock(check_out_at)

    application = check_out(application=application, volunteer=volunteer)

    # Refresh volunteer after the cascade.
    volunteer = get_success_data(
        api_client.get_volunteer(volunteer["id"], make_skilladmin_headers())
    )

    return {
        **setup,
        "activity": get_success_data(
            api_client.get_activity(activity["id"], make_skilladmin_headers())
        ),
        "application": application,
        "volunteer": volunteer,
    }


# ===========================================================================
# Tier 4: HourAdjustment (PRD §3.7)
# ===========================================================================
def file_hour_adjustment(
    *,
    application: Dict[str, Any],
    organizer: Dict[str, Any],
    delta_hours: float,
    reason: str = "Volunteer assisted with extra cleanup duties.",
) -> Dict[str, Any]:
    return get_success_data(
        api_client.file_hour_adjustment(
            file_hour_adjustment_payload(
                application_id=application["id"],
                delta_hours=delta_hours,
                reason=reason,
            ),
            make_organizer_headers(organizer["id"]),
        )
    )


def approve_hour_adjustment(adjustment_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.approve_hour_adjustment(adjustment_id, make_skilladmin_headers())
    )


def reject_hour_adjustment(adjustment_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.reject_hour_adjustment(adjustment_id, make_skilladmin_headers())
    )


# ===========================================================================
# Tier 4b: Point mall + redemption (PRD §3.7)
# ===========================================================================
def create_point_mall_item(
    *,
    point_cost: int = 10,
    stock: int = 5,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_point_mall_item(
            create_point_mall_item_payload(
                point_cost=point_cost, stock=stock, **overrides
            ),
            make_skilladmin_headers(),
        )
    )


def archive_point_mall_item(item_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.archive_point_mall_item(item_id, make_skilladmin_headers())
    )


def restock_item(item_id: str, *, delta: int) -> Dict[str, Any]:
    from .factories import restock_payload
    return get_success_data(
        api_client.restock_point_mall_item(
            item_id, restock_payload(delta=delta), make_skilladmin_headers()
        )
    )


def create_redemption_order(
    *,
    volunteer: Dict[str, Any],
    item_id: str,
    quantity: int = 1,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_redemption_order(
            create_redemption_order_payload(item_id=item_id, quantity=quantity),
            make_volunteer_headers(volunteer["id"]),
        )
    )


def fulfill_redemption_order(order_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.fulfill_redemption_order(order_id, make_skilladmin_headers())
    )


def cancel_redemption_order(
    *,
    order: Dict[str, Any],
    volunteer: Dict[str, Any],
) -> Dict[str, Any]:
    return get_success_data(
        api_client.cancel_redemption_order(
            order["id"], make_volunteer_headers(volunteer["id"])
        )
    )


# ===========================================================================
# Tier 5: Certificates (PRD §3.9)
# ===========================================================================
def create_certificate_template(
    *,
    min_hours: float = 5.00,
    min_completed_activities: int = 1,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_certificate_template(
            create_certificate_template_payload(
                min_hours=min_hours,
                min_completed_activities=min_completed_activities,
                **overrides,
            ),
            make_skilladmin_headers(),
        )
    )


def issue_certificate(
    *,
    template: Dict[str, Any],
    volunteer: Dict[str, Any],
) -> Dict[str, Any]:
    return get_success_data(
        api_client.issue_certificate(
            issue_certificate_payload(
                template_id=template["id"], volunteer_id=volunteer["id"]
            ),
            make_skilladmin_headers(),
        )
    )


def reissue_certificate(certificate_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.reissue_certificate(certificate_id, make_skilladmin_headers())
    )


def revoke_certificate(certificate_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.revoke_certificate(certificate_id, make_skilladmin_headers())
    )


# ===========================================================================
# Audit + sync helpers
# ===========================================================================
def list_audit_logs(**params: Any) -> List[Dict[str, Any]]:
    res = api_client.list_audit_logs(make_skilladmin_headers(), params=params or None)
    body = res.json()
    return list(body.get("data", []))


def list_partner_sync_events(**params: Any) -> List[Dict[str, Any]]:
    res = api_client.list_partner_sync_events(
        make_skilladmin_headers(), params=params or None
    )
    body = res.json()
    return list(body.get("data", []))


# ===========================================================================
# Read helpers
# ===========================================================================
def get_volunteer(volunteer_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_volunteer(volunteer_id, make_skilladmin_headers())
    )


def get_activity(activity_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_activity(activity_id, make_skilladmin_headers())
    )


def get_application(application_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_application(application_id, make_skilladmin_headers())
    )


__all__ = [
    # Time helpers
    "iso_z",
    "parse_iso",
    "add_seconds",
    "add_minutes",
    "add_hours",
    "add_days",
    # Clock
    "reset_clock_to_baseline",
    "advance_clock",
    "get_clock",
    # Tier 1
    "create_volunteer",
    "verify_identity",
    "reject_identity",
    "create_verified_volunteer",
    "create_volunteer_with_clearance",
    "create_skill",
    "declare_and_approve_skill",
    "equip_volunteer_with_skills",
    # Tier 1c — Activity
    "make_activity_times",
    "create_draft_activity",
    "submit_activity",
    "approve_activity",
    "reject_activity",
    "define_activity_role",
    "publish_activity",
    "advance_to_recruiting",
    "advance_to_running",
    "advance_to_completed",
    # Tier 2 — Application
    "apply_to_activity",
    "approve_application",
    "reject_application",
    "withdraw_application",
    "check_in_via_site_code",
    "check_in_via_gps",
    "request_leave",
    "check_out",
    "manual_correction",
    # Tier 3 — Composites
    "setup_organizer",
    "setup_recruiting_activity",
    "setup_running_activity_with_approved_volunteer",
    "setup_completed_application",
    # Tier 4 — HourAdjustment + point mall
    "file_hour_adjustment",
    "approve_hour_adjustment",
    "reject_hour_adjustment",
    "create_point_mall_item",
    "archive_point_mall_item",
    "restock_item",
    "create_redemption_order",
    "fulfill_redemption_order",
    "cancel_redemption_order",
    # Tier 5 — Certificates
    "create_certificate_template",
    "issue_certificate",
    "reissue_certificate",
    "revoke_certificate",
    # Audit + sync
    "list_audit_logs",
    "list_partner_sync_events",
    # Reads
    "get_volunteer",
    "get_activity",
    "get_application",
]
