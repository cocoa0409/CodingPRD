"""Composite setup helpers — multi-step preambles tests can reuse.

The camp pipeline is long: family create -> guardian create -> child
create -> emergency contact + medical authorization + pickup
authorization -> session create -> session open -> enrollment create
(PENDING_AUTH) -> enrollment confirm -> ... -> session close /
cancel / clock-driven side effects. Most interesting test claims need
the system in a late-pipeline state.

IDENTITY THREADING — PRD §2.1:

- ProgramAdmin is OPAQUE — shared admin_headers constant is canonical
  for every admin-only call.

- Guardian is ENTITY-BACKED. Every Guardian-driven call (create child,
  create emergency contact, create authorization, revoke authorization,
  create enrollment, confirm enrollment, cancel enrollment, GET own
  family, GET own family invoice) MUST mint headers via
  make_guardian_headers(guardian["id"]) — never via the shared
  GUARDIAN_FALLBACK_ID constant. The fixtures here remember the family's
  primary Guardian.id so consumer tests can route guardian-acting calls
  through this header builder.

Setup calls use get_success_data (a lenient 2xx validator), so a
failed setup surfaces as "Setup failed" rather than a confusing test
assertion failure downstream.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    clock_advance_payload,
    create_authorization_payload,
    create_child_payload,
    create_emergency_contact_payload,
    create_enrollment_payload,
    create_family_payload,
    create_guardian_payload,
    create_scholarship_payload,
    create_session_payload,
    dob_for_age,
    iso_date,
    iso_offset,
    iso_utc,
    next_monday,
    parse_iso,
    set_weather_payload,
)
from .test_users import TEST_USERS, make_guardian_headers


# ===========================================================================
# Clock helpers — PRD §2.7 (ProgramAdmin-only for advance)
# ===========================================================================
def advance_clock_to(iso_timestamp: str,
                     headers: Optional[Dict[str, str]] = None
                     ) -> Dict[str, Any]:
    """POST /_clock/advance. PRD §2.7: ProgramAdmin only."""
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.clock_advance(
        clock_advance_payload(iso_timestamp=iso_timestamp), headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 1: Family + primary guardian
# ===========================================================================
def create_family(
    *,
    household_name: Optional[str] = None,
    primary_email: Optional[str] = None,
    residency_status: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /camp/families — ProgramAdmin only per PRD §4."""
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.create_family(
        create_family_payload(
            household_name=household_name,
            primary_email=primary_email,
            residency_status=residency_status,
        ),
        headers,
    )
    return get_success_data(resp)


def create_guardian(
    *,
    family: Dict[str, Any],
    full_name: Optional[str] = None,
    phone: Optional[str] = None,
    relationship: str = "PARENT",
    is_primary: Optional[bool] = True,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /camp/families/{family_id}/guardians.

    PRD §4: roles ProgramAdmin or Guardian. Defaults to admin so the
    fixture sequence works for fresh families that have no guardians yet
    (a Guardian-acting caller cannot create their own first row).
    """
    headers = headers or TEST_USERS["admin_headers"]
    payload = create_guardian_payload(
        full_name=full_name, phone=phone, relationship=relationship,
        is_primary=is_primary,
    )
    resp = api_client.create_guardian(family["id"], payload, headers)
    return get_success_data(resp)


def setup_family_with_primary_guardian(
    *,
    residency_status: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Compose: family + primary guardian. Returns (family, guardian).

    PRD §3.1: "Each family has exactly one primary contact at any time
    — the row whose is_primary is true. When a new guardian is created
    with is_primary set to true, any previously primary guardian on the
    same family is silently demoted."
    """
    family = create_family(residency_status=residency_status)
    guardian = create_guardian(family=family, is_primary=True)
    return family, guardian


# ===========================================================================
# Tier 2: Child + emergency contact + active medical & pickup authorizations
# ===========================================================================
def create_child(
    *,
    family: Dict[str, Any],
    age_years: Optional[int] = None,
    date_of_birth: Optional[str] = None,
    reference_date: Optional[str] = None,
    full_name: Optional[str] = None,
    actor_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /camp/families/{family_id}/children.

    PRD §4: roles ProgramAdmin or Guardian. Defaults to admin so setup
    can run before a primary guardian is known to the test.

    Identity threading: when a Guardian acts (actor_headers supplied),
    the caller is responsible for minting the headers via
    make_guardian_headers(guardian["id"]).
    """
    actor_headers = actor_headers or TEST_USERS["admin_headers"]
    payload = create_child_payload(
        full_name=full_name,
        age_years=age_years,
        reference_date=reference_date,
        date_of_birth=date_of_birth,
    )
    resp = api_client.create_child(family["id"], payload, actor_headers)
    return get_success_data(resp)


def add_emergency_contact(
    *,
    child: Dict[str, Any],
    priority: int = 1,
    full_name: Optional[str] = None,
    phone: Optional[str] = None,
    relationship: str = "aunt",
    actor_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /camp/children/{child_id}/emergency-contacts."""
    actor_headers = actor_headers or TEST_USERS["admin_headers"]
    payload = create_emergency_contact_payload(
        priority=priority, full_name=full_name, phone=phone,
        relationship=relationship,
    )
    resp = api_client.create_emergency_contact(
        child["id"], payload, actor_headers,
    )
    return get_success_data(resp)


def create_authorization(
    *,
    child: Dict[str, Any],
    guardian: Dict[str, Any],
    kind: str = "MEDICAL",
    effective_at: Optional[str] = None,
    expires_at: Optional[str] = None,
    effective_offset_minutes: int = -60,
    expires_offset_days: int = 365,
    actor_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /camp/children/{child_id}/authorizations.

    PRD §3.2: "guardian_id pointing at the guardian granting the
    permission (who must belong to the same family as the child,
    otherwise the request is rejected with ERR_FAMILY_MISMATCH)".
    """
    actor_headers = actor_headers or TEST_USERS["admin_headers"]
    payload = create_authorization_payload(
        guardian_id=guardian["id"], kind=kind,
        effective_at=effective_at, expires_at=expires_at,
        effective_offset_minutes=effective_offset_minutes,
        expires_offset_days=expires_offset_days,
    )
    resp = api_client.create_authorization(
        child["id"], payload, actor_headers,
    )
    return get_success_data(resp)


def setup_authorized_child(
    *,
    family: Dict[str, Any],
    guardian: Dict[str, Any],
    age_years: Optional[int] = None,
    date_of_birth: Optional[str] = None,
    reference_date: Optional[str] = None,
    full_name: Optional[str] = None,
    include_medical: bool = True,
    include_pickup: bool = True,
    include_emergency_contact: bool = True,
    expires_offset_days: int = 365,
) -> Dict[str, Any]:
    """Compose: child + emergency contact + medical authorization +
    pickup authorization. Returns the freshly-read Child so derived
    fields (medical_authorization_status, pickup_authorization_status,
    emergency_contact_count) reflect the seeded state.

    All four prerequisites in PRD §3.4 confirmation gate are satisfied
    when include_medical and include_pickup are True AND
    include_emergency_contact is True AND the child's age lies in
    [age_min, age_max] of the session under test.
    """
    child = create_child(
        family=family, age_years=age_years, date_of_birth=date_of_birth,
        reference_date=reference_date, full_name=full_name,
    )
    if include_emergency_contact:
        add_emergency_contact(child=child, priority=1)
    if include_medical:
        create_authorization(
            child=child, guardian=guardian, kind="MEDICAL",
            expires_offset_days=expires_offset_days,
        )
    if include_pickup:
        create_authorization(
            child=child, guardian=guardian, kind="PICKUP",
            expires_offset_days=expires_offset_days,
        )
    # Re-read the child so derived fields are projected.
    refreshed = get_success_data(
        api_client.get_child(child["id"], TEST_USERS["admin_headers"]),
    )
    return refreshed


# ===========================================================================
# Tier 3: Session create + open
# ===========================================================================
def create_session(
    *,
    title: Optional[str] = None,
    kind: str = "AFTERSCHOOL",
    age_min: int = 5,
    age_max: int = 12,
    reference_date: Optional[str] = None,
    weekly_capacity: int = 10,
    week_start: Optional[str] = None,
    week_count: int = 1,
    base_weekly_fee_cents: int = 10_000,
    rainy_day_pool_per_week: int = 0,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /camp/sessions — ProgramAdmin only per PRD §4."""
    headers = headers or TEST_USERS["admin_headers"]
    payload = create_session_payload(
        title=title, kind=kind, age_min=age_min, age_max=age_max,
        reference_date=reference_date, weekly_capacity=weekly_capacity,
        week_start=week_start, week_count=week_count,
        base_weekly_fee_cents=base_weekly_fee_cents,
        rainy_day_pool_per_week=rainy_day_pool_per_week,
    )
    resp = api_client.create_session(payload, headers)
    return get_success_data(resp)


def open_session(
    *,
    session: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /camp/sessions/{id}/open — ProgramAdmin only per PRD §4."""
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.open_session(session["id"], headers)
    return get_success_data(resp)


def setup_open_session(
    *,
    kind: str = "AFTERSCHOOL",
    age_min: int = 5,
    age_max: int = 12,
    weekly_capacity: int = 10,
    week_count: int = 1,
    base_weekly_fee_cents: int = 10_000,
    rainy_day_pool_per_week: int = 0,
    reference_date: Optional[str] = None,
    week_start: Optional[str] = None,
) -> Dict[str, Any]:
    """Compose: session create + open. Returns the OPEN session."""
    session = create_session(
        kind=kind, age_min=age_min, age_max=age_max,
        weekly_capacity=weekly_capacity, week_count=week_count,
        base_weekly_fee_cents=base_weekly_fee_cents,
        rainy_day_pool_per_week=rainy_day_pool_per_week,
        reference_date=reference_date, week_start=week_start,
    )
    return open_session(session=session)


# ===========================================================================
# Tier 4: Enrollment lifecycle
# ===========================================================================
def create_enrollment(
    *,
    child: Dict[str, Any],
    session: Dict[str, Any],
    week_index: int = 0,
    actor_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /camp/enrollments.

    PRD §4: roles ProgramAdmin or Guardian. Defaults to admin for setup
    speed; Guardian-acting tests pass actor_headers minted from the
    guardian's id.
    """
    actor_headers = actor_headers or TEST_USERS["admin_headers"]
    payload = create_enrollment_payload(
        child_id=child["id"], session_id=session["id"],
        week_index=week_index,
    )
    resp = api_client.create_enrollment(payload, actor_headers)
    return get_success_data(resp)


def confirm_enrollment(
    *,
    enrollment: Dict[str, Any],
    actor_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /camp/enrollments/{id}/confirm.

    PRD §4: roles ProgramAdmin or Guardian.
    """
    actor_headers = actor_headers or TEST_USERS["admin_headers"]
    resp = api_client.confirm_enrollment(
        enrollment["id"], actor_headers,
    )
    return get_success_data(resp)


def cancel_enrollment(
    *,
    enrollment: Dict[str, Any],
    actor_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /camp/enrollments/{id}/cancel.

    PRD §4: roles ProgramAdmin or Guardian.
    """
    actor_headers = actor_headers or TEST_USERS["admin_headers"]
    resp = api_client.cancel_enrollment(
        enrollment["id"], actor_headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 5: ScholarshipAward
# ===========================================================================
def grant_scholarship(
    *,
    family: Dict[str, Any],
    total_credit_cents: int = 5_000,
    granted_for_kind: str = "ANY",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /camp/families/{family_id}/scholarships — ProgramAdmin only."""
    headers = headers or TEST_USERS["admin_headers"]
    payload = create_scholarship_payload(
        total_credit_cents=total_credit_cents,
        granted_for_kind=granted_for_kind,
    )
    resp = api_client.create_scholarship(family["id"], payload, headers)
    return get_success_data(resp)


def revoke_scholarship(
    *,
    scholarship: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /camp/scholarships/{id}/revoke — ProgramAdmin only."""
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.revoke_scholarship(scholarship["id"], headers)
    return get_success_data(resp)


# ===========================================================================
# Tier 6: SessionDay weather
# ===========================================================================
def set_weather(
    *,
    session_day: Dict[str, Any],
    weather_status: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /camp/session-days/{id}/set-weather — ProgramAdmin only."""
    headers = headers or TEST_USERS["admin_headers"]
    payload = set_weather_payload(weather_status=weather_status)
    resp = api_client.set_weather(session_day["id"], payload, headers)
    return get_success_data(resp)


def list_session_days(
    *,
    session: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """Convenience: derive the SessionDay rows by reading the session
    roster's parent. PRD §3.3: opening a session materializes one
    SessionDay row per business day per ISO week. Tests need to locate
    these rows by (week_index, day_date).

    The PRD does not expose a list-session-days endpoint, so we read
    individual session-days via the open session's response if
    available, else re-fetch the session and look at its days via the
    PRD-prescribed GET /camp/session-days/{id} endpoint. In practice
    callers will use enumerate_session_days() below if the
    implementation exposes day ids on the session.
    """
    headers = headers or TEST_USERS["admin_headers"]
    # Some implementations return session_days on the session payload
    # after opening. If not, the test cannot list them generically.
    if "session_days" in session and isinstance(
        session["session_days"], list
    ):
        return session["session_days"]
    return []


def get_session_days(
    *,
    session: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """Re-read the session and extract the session_days list if the
    implementation surfaces it on the session response."""
    headers = headers or TEST_USERS["admin_headers"]
    refreshed = get_success_data(
        api_client.get_session(session["id"], headers),
    )
    if "session_days" in refreshed and isinstance(
        refreshed["session_days"], list
    ):
        return refreshed["session_days"]
    return []


# ===========================================================================
# Tier 7: Composite scenarios for common test claims
# ===========================================================================
def setup_ready_to_confirm(
    *,
    age_years: int = 8,
    weekly_capacity: int = 10,
    base_weekly_fee_cents: int = 10_000,
    week_count: int = 1,
    kind: str = "AFTERSCHOOL",
    age_min: int = 5,
    age_max: int = 12,
    week_index: int = 0,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
           Dict[str, Any]]:
    """Compose: family + primary guardian + child (auth/contact ready) +
    OPEN session + PENDING_AUTH enrollment.

    Returns (family, guardian, child, session, enrollment).

    All four confirmation gate prerequisites (medical, pickup, emergency
    contact, age) are satisfied so confirm_enrollment() on the returned
    enrollment immediately transitions PENDING_AUTH -> CONFIRMED.
    """
    family, guardian = setup_family_with_primary_guardian()
    session = setup_open_session(
        kind=kind, age_min=age_min, age_max=age_max,
        weekly_capacity=weekly_capacity, week_count=week_count,
        base_weekly_fee_cents=base_weekly_fee_cents,
    )
    child = setup_authorized_child(
        family=family, guardian=guardian, age_years=age_years,
        reference_date=session["reference_date"],
    )
    enrollment = create_enrollment(
        child=child, session=session, week_index=week_index,
    )
    return family, guardian, child, session, enrollment


def setup_confirmed_enrollment(
    *,
    age_years: int = 8,
    weekly_capacity: int = 10,
    base_weekly_fee_cents: int = 10_000,
    kind: str = "AFTERSCHOOL",
    age_min: int = 5,
    age_max: int = 12,
    week_count: int = 1,
    week_index: int = 0,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
           Dict[str, Any]]:
    """Compose: setup_ready_to_confirm + confirm.

    Returns (family, guardian, child, session, CONFIRMED enrollment).
    """
    family, guardian, child, session, enrollment = setup_ready_to_confirm(
        age_years=age_years, weekly_capacity=weekly_capacity,
        base_weekly_fee_cents=base_weekly_fee_cents, kind=kind,
        age_min=age_min, age_max=age_max, week_count=week_count,
        week_index=week_index,
    )
    confirmed = confirm_enrollment(enrollment=enrollment)
    return family, guardian, child, session, confirmed


def setup_family_with_n_authorized_children(
    *,
    n: int,
    age_years: int = 8,
    reference_date: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    """Compose: family + primary guardian + N authorized children
    sharing the same guardian. Used for the sibling-discount tier
    tests.

    Returns (family, guardian, [child_1, ..., child_n]).
    """
    family, guardian = setup_family_with_primary_guardian()
    children: List[Dict[str, Any]] = []
    for _ in range(n):
        children.append(setup_authorized_child(
            family=family, guardian=guardian, age_years=age_years,
            reference_date=reference_date,
        ))
    return family, guardian, children


def setup_n_families_each_with_authorized_child(
    *,
    n: int,
    age_years: int = 8,
    reference_date: Optional[str] = None,
) -> List[Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]]:
    """Compose: N independent families, each with a primary guardian
    and one authorized child. Used for capacity / waitlist tests where
    children must NOT be siblings (each in its own family) so the
    sibling discount does not fire.

    Returns [(family, guardian, child), ...].
    """
    out: List[Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]] = []
    for _ in range(n):
        family, guardian = setup_family_with_primary_guardian()
        child = setup_authorized_child(
            family=family, guardian=guardian, age_years=age_years,
            reference_date=reference_date,
        )
        out.append((family, guardian, child))
    return out


def re_get_enrollment(
    enrollment_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["admin_headers"]
    return get_success_data(
        api_client.get_enrollment(enrollment_id, headers),
    )


def re_get_child(
    child_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["admin_headers"]
    return get_success_data(api_client.get_child(child_id, headers))


def re_get_session(
    session_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["admin_headers"]
    return get_success_data(
        api_client.get_session(session_id, headers),
    )


def re_get_family(
    family_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["admin_headers"]
    return get_success_data(
        api_client.get_family(family_id, headers),
    )


def find_scholarship_in_response(data: Dict[str, Any]) -> Dict[str, Any]:
    """Re-fetch the scholarship's current state via a list call on the
    session. The PRD does not expose a GET /camp/scholarships/{id}
    endpoint, but the award's fields appear inline on every Enrollment
    that references it via scholarship_award_id. Callers usually need
    only the consumed_credit_cents and status, which they read from
    the scholarship's POST response or by re-issuing the grant call.
    """
    return data


__all__ = [
    "advance_clock_to",
    "create_family",
    "create_guardian",
    "setup_family_with_primary_guardian",
    "create_child",
    "add_emergency_contact",
    "create_authorization",
    "setup_authorized_child",
    "create_session",
    "open_session",
    "setup_open_session",
    "create_enrollment",
    "confirm_enrollment",
    "cancel_enrollment",
    "grant_scholarship",
    "revoke_scholarship",
    "set_weather",
    "list_session_days",
    "get_session_days",
    "setup_ready_to_confirm",
    "setup_confirmed_enrollment",
    "setup_family_with_n_authorized_children",
    "setup_n_families_each_with_authorized_child",
    "re_get_enrollment",
    "re_get_child",
    "re_get_session",
    "re_get_family",
]
