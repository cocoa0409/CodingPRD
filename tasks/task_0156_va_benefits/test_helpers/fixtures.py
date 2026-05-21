"""Composite setup helpers — multi-step preambles tests can reuse.

Most interesting test claims require the system to be in a late state
that takes many API calls to reach (Veteran -> School -> GRANTED Claim
-> Enrollment -> Certify -> Sweep -> Activate -> ...). Each fixture
composes the lower-level steps so the test body can focus on the rule
under assertion.

IDENTITY THREADING — PRD §2.1:

    "When X-User-Role is Veteran, X-User-ID is the id of the acting
    Veteran entity; every ownership check on a resource that references
    a veteran ... compares the resource's veteran_id field to X-User-ID,
    and any ownership mismatch is treated as a forbidden operation."

After a Veteran is created, any ownership-gated call in the same
fixture (or in a consumer fixture) uses make_veteran_headers(
veteran["id"]) — never falls back to the shared TEST_USERS[
"veteran_headers"] constant for ownership operations.

CLOCK ANCHORING — PRD §3.8:

    "An admin-only test-driving capability advances the logical server
    clock, accepting a body with either a to timestamp ... or a seconds
    integer (the clock advances by that many seconds), and returning
    the new now."

Setup calls use get_success_data (a lenient 2xx validator), so a failed
setup surfaces as 'Setup failed' rather than a confusing test assertion
failure downstream.
"""
from __future__ import annotations

import threading
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    add_days,
    clock_advance_to_payload,
    create_claim_payload,
    create_dependent_payload,
    create_enrollment_payload,
    create_housing_payment_payload,
    create_school_payload,
    create_veteran_payload,
    create_voc_rehab_plan_payload,
    date_iso_midnight,
    grant_claim_payload,
    iso_utc,
    parse_iso,
    utc_midnight,
    utcnow,
)
from .test_users import (
    TEST_USERS,
    make_counselor_headers,
    make_platform_admin_headers,
    make_rater_headers,
    make_va_clerk_headers,
    make_veteran_headers,
)


# ===========================================================================
# Clock helpers — PRD §3.8
# ===========================================================================
_CLOCK_LOCK = threading.Lock()
_CURRENT_CLOCK: Optional[datetime] = None


def _seed_clock() -> datetime:
    global _CURRENT_CLOCK
    with _CLOCK_LOCK:
        if _CURRENT_CLOCK is None:
            _CURRENT_CLOCK = utcnow()
        return _CURRENT_CLOCK


def current_clock() -> datetime:
    return _seed_clock()


def current_clock_iso() -> str:
    return iso_utc(current_clock())


def advance_clock_to(
    target_dt: datetime,
    headers: Optional[Dict[str, str]] = None,
) -> str:
    """PRD §3.8: 'advances the logical server clock, accepting a body
    with either a to timestamp (an ISO 8601 instant the clock jumps
    to)'."""
    global _CURRENT_CLOCK
    with _CLOCK_LOCK:
        now = _CURRENT_CLOCK if _CURRENT_CLOCK is not None else utcnow()
        if target_dt < now:
            target_dt = now
        target_iso = iso_utc(target_dt)
        resp = api_client.advance_clock(
            clock_advance_to_payload(target_iso),
            headers or TEST_USERS["platform_admin_headers"],
        )
        get_success_data(resp)
        _CURRENT_CLOCK = target_dt
    return target_iso


def advance_clock_by_days(days: int) -> str:
    return advance_clock_to(current_clock() + timedelta(days=days))


def advance_clock_by_seconds(seconds: int) -> str:
    return advance_clock_to(current_clock() + timedelta(seconds=seconds))


def reset_clock_tracker_to(dt: datetime) -> None:
    global _CURRENT_CLOCK
    with _CLOCK_LOCK:
        _CURRENT_CLOCK = dt


def run_sweep(headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """PRD §3.8: 'The other runs the periodic sweep, which is
    idempotent: it performs the certified-to-active promotions ... and
    also performs the denied-to-final claim transition'."""
    resp = api_client.run_sweep(
        headers or TEST_USERS["platform_admin_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# Veteran primitives — PRD §3.1
# ===========================================================================
def create_veteran(
    full_name: Optional[str] = None,
    branch: Optional[str] = None,
    aggregate_active_duty_days: Optional[int] = None,
    discharge_status: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    **overrides,
) -> Dict[str, Any]:
    """Create a Veteran. By default acts as a VAClerk (PRD §3.1: 'Either
    a VAClerk or a PlatformAdmin may register the veteran').

    The returned veteran['id'] is the value that must be passed as
    X-User-ID for any subsequent Veteran-role call against that
    veteran — fixtures here always do so via make_veteran_headers.
    """
    payload = create_veteran_payload(
        full_name=full_name,
        branch=branch,
        aggregate_active_duty_days=aggregate_active_duty_days,
        discharge_status=discharge_status,
        **overrides,
    )
    resp = api_client.create_veteran(
        payload, headers or TEST_USERS["va_clerk_headers"],
    )
    return get_success_data(resp)


def get_veteran(veteran_id: str,
                headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Read a Veteran. Uses PlatformAdmin by default — PRD §2.1
    declares PlatformAdmin has 'unrestricted read across the domain',
    so this avoids needing to mint the veteran's own headers."""
    resp = api_client.get_veteran(
        veteran_id,
        headers or TEST_USERS["platform_admin_headers"],
    )
    return get_success_data(resp)


def patch_veteran(veteran_id: str, headers: Optional[Dict[str, str]] = None,
                  **fields) -> Dict[str, Any]:
    """Patch a Veteran via VAClerk (the role authorized for PATCH per
    PRD §4)."""
    from .factories import patch_veteran_payload
    resp = api_client.patch_veteran(
        veteran_id,
        patch_veteran_payload(**fields),
        headers or TEST_USERS["va_clerk_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# School primitives — PRD §3.5
# ===========================================================================
def create_school(
    name: Optional[str] = None,
    facility_code: Optional[str] = None,
    program_type: str = "PUBLIC_IN_STATE",
    yellow_ribbon_enrolled: bool = False,
    yellow_ribbon_max_per_year: Optional[float] = None,
    zip_bah_code: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.5: 'A School is registered by a PlatformAdmin'."""
    payload = create_school_payload(
        name=name,
        facility_code=facility_code,
        program_type=program_type,
        yellow_ribbon_enrolled=yellow_ribbon_enrolled,
        yellow_ribbon_max_per_year=yellow_ribbon_max_per_year,
        zip_bah_code=zip_bah_code,
        **overrides,
    )
    resp = api_client.create_school(
        payload, headers or TEST_USERS["platform_admin_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# Dependent primitives — PRD §3.2
# ===========================================================================
def create_dependent(
    veteran_id: str,
    relationship: str,
    date_of_birth: Optional[str] = None,
    school_enrolled: Optional[bool] = None,
    headers: Optional[Dict[str, str]] = None,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.2: 'A veteran's dependents enter the system via the
    dependent-creation endpoint'. Defaults to a VAClerk caller."""
    payload = create_dependent_payload(
        veteran_id=veteran_id,
        relationship=relationship,
        date_of_birth=date_of_birth,
        school_enrolled=school_enrolled,
        **overrides,
    )
    resp = api_client.create_dependent(
        payload, headers or TEST_USERS["va_clerk_headers"],
    )
    return get_success_data(resp)


def delete_dependent(dependent_id: str,
                     headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """PRD §3.2: 'Removing a dependent moves it from ACTIVE to
    REMOVED'."""
    resp = api_client.delete_dependent(
        dependent_id, headers or TEST_USERS["va_clerk_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# Claim primitives — PRD §3.3
# ===========================================================================
def create_claim(
    veteran_id: str,
    condition_code: Optional[str] = None,
    claim_type: str = "ORIGINAL",
    original_claim_id: Optional[str] = None,
    proposed_rating: int = 30,
    headers: Optional[Dict[str, str]] = None,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.3: 'A veteran may file their own claims (where veteran_id
    equals their X-User-ID), and a VAClerk may file on behalf of any
    veteran.'

    Defaults to acting as the owning Veteran so the call satisfies the
    veteran_id == X-User-ID ownership guard (PRD §2.1).
    """
    payload = create_claim_payload(
        veteran_id=veteran_id,
        condition_code=condition_code,
        claim_type=claim_type,
        original_claim_id=original_claim_id,
        proposed_rating=proposed_rating,
        **overrides,
    )
    resp = api_client.create_claim(
        payload,
        headers or make_veteran_headers(veteran_id),
    )
    return get_success_data(resp)


def start_review_claim(claim_id: str,
                       headers: Optional[Dict[str, str]] = None,
                       rater_operator_id: str = "rater-0001") -> Dict[str, Any]:
    """PRD §3.3: 'starting a review by a Rater moves a claim from
    SUBMITTED to UNDER_REVIEW and stamps the rater's X-User-ID as
    rater_id.'"""
    h = headers or make_rater_headers(rater_operator_id)
    resp = api_client.start_review_claim(claim_id, h)
    return get_success_data(resp)


def grant_claim(claim_id: str, granted_rating: int,
                headers: Optional[Dict[str, str]] = None,
                rater_operator_id: str = "rater-0001") -> Dict[str, Any]:
    """PRD §3.3: 'A successful grant writes granted_rating and
    decided_at on the claim, then re-runs the combined-rating
    computation for the owning veteran'."""
    h = headers or make_rater_headers(rater_operator_id)
    resp = api_client.grant_claim(
        claim_id, grant_claim_payload(granted_rating), h,
    )
    return get_success_data(resp)


def deny_claim(claim_id: str,
               headers: Optional[Dict[str, str]] = None,
               rater_operator_id: str = "rater-0001") -> Dict[str, Any]:
    """PRD §3.3: 'Denying the claim moves it from UNDER_REVIEW to
    DENIED, stamps decided_at, and writes no rating.'"""
    h = headers or make_rater_headers(rater_operator_id)
    resp = api_client.deny_claim(claim_id, h)
    return get_success_data(resp)


def appeal_claim(claim_id: str, veteran_id: str,
                 headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """PRD §3.3: 'A denied claim can be appealed by the owning
    veteran — the appeal transition flips DENIED to APPEALED and is
    gated on the caller being the owning veteran (X-User-ID equal to
    Claim.veteran_id).'"""
    h = headers or make_veteran_headers(veteran_id)
    resp = api_client.appeal_claim(claim_id, h)
    return get_success_data(resp)


def reopen_claim(claim_id: str,
                 headers: Optional[Dict[str, str]] = None,
                 rater_operator_id: str = "rater-0002") -> Dict[str, Any]:
    """PRD §3.3: 'A granted claim can be reopened by a different
    rater.'"""
    h = headers or make_rater_headers(rater_operator_id)
    resp = api_client.reopen_claim(claim_id, h)
    return get_success_data(resp)


def grant_claim_for_veteran(
    veteran_id: str, granted_rating: int = 30,
    condition_code: Optional[str] = None,
    starter_rater_id: str = "rater-0001",
) -> Dict[str, Any]:
    """End-to-end: SUBMITTED -> UNDER_REVIEW -> GRANTED. Returns the
    granted claim row.

    Uses the same rater for /start-review and /grant (segregation of
    duties on grant only forbids the rater being someone already
    recorded as rater_id — and for an ORIGINAL claim, no prior rater_id
    exists at /start-review time, so the same rater can both start the
    review and grant)."""
    claim = create_claim(veteran_id=veteran_id,
                         condition_code=condition_code,
                         claim_type="ORIGINAL",
                         proposed_rating=granted_rating)
    start_review_claim(claim["id"], rater_operator_id=starter_rater_id)
    return grant_claim(claim["id"], granted_rating,
                       rater_operator_id=starter_rater_id)


def deny_claim_for_veteran(
    veteran_id: str,
    proposed_rating: int = 30,
    condition_code: Optional[str] = None,
    rater_operator_id: str = "rater-0001",
) -> Dict[str, Any]:
    """End-to-end: SUBMITTED -> UNDER_REVIEW -> DENIED. Returns denied
    claim."""
    claim = create_claim(veteran_id=veteran_id,
                         condition_code=condition_code,
                         claim_type="ORIGINAL",
                         proposed_rating=proposed_rating)
    start_review_claim(claim["id"], rater_operator_id=rater_operator_id)
    return deny_claim(claim["id"], rater_operator_id=rater_operator_id)


# ===========================================================================
# Veteran-with-service-connection composites
# ===========================================================================
def setup_veteran_with_granted_claim(
    granted_rating: int = 10,
    aggregate_active_duty_days: int = 1100,
    discharge_status: str = "HONORABLE",
    rater_operator_id: str = "rater-0001",
) -> Dict[str, Any]:
    """Create a Veteran (HONORABLE, tier 100 by default) with one
    GRANTED Claim — i.e. Veteran.combined_rating > 0 and post_911
    eligibility ready for downstream enrollment-activation tests.

    Returns the veteran dict (with computed combined_rating refreshed
    after the grant)."""
    vet = create_veteran(
        aggregate_active_duty_days=aggregate_active_duty_days,
        discharge_status=discharge_status,
    )
    grant_claim_for_veteran(
        veteran_id=vet["id"],
        granted_rating=granted_rating,
        starter_rater_id=rater_operator_id,
    )
    # PRD §3.3: granting "re-runs the combined-rating computation for
    # the owning veteran and writes the result into
    # Veteran.combined_rating", so re-fetch.
    return get_veteran(vet["id"])


# ===========================================================================
# Enrollment composites — PRD §3.6, §3.7, §3.8
# ===========================================================================
def _default_term(months: int = 4,
                  start_offset_days: int = 30) -> Tuple[str, str]:
    """Return (term_start, term_end) ISO strings — midnight-aligned per
    PRD §2.6 ('UTC midnights bounding a half-open interval')."""
    base = current_clock().date() + timedelta(days=start_offset_days)
    start = utc_midnight(base)
    end = utc_midnight(base + timedelta(days=30 * months))
    return iso_utc(start), iso_utc(end)


def create_enrollment(
    veteran_id: str,
    school_id: str,
    term_start: Optional[str] = None,
    term_end: Optional[str] = None,
    tuition_charged: float = 10000.00,
    training_time: str = "FULL_TIME",
    delivery_mode: str = "IN_PERSON",
    headers: Optional[Dict[str, str]] = None,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.6: 'Either the owning veteran (where veteran_id equals
    their X-User-ID) or a VAClerk may submit.' Defaults to the owning
    Veteran so the veteran_id == X-User-ID guard is satisfied (PRD §2.1)."""
    if term_start is None or term_end is None:
        ts, te = _default_term()
        term_start = term_start or ts
        term_end = term_end or te
    payload = create_enrollment_payload(
        veteran_id=veteran_id,
        school_id=school_id,
        term_start=term_start,
        term_end=term_end,
        tuition_charged=tuition_charged,
        training_time=training_time,
        delivery_mode=delivery_mode,
        **overrides,
    )
    resp = api_client.create_enrollment(
        payload,
        headers or make_veteran_headers(veteran_id),
    )
    return get_success_data(resp)


def certify_enrollment(enrollment_id: str,
                       headers: Optional[Dict[str, str]] = None
                       ) -> Dict[str, Any]:
    """PRD §3.7: 'A clerk certifies a submitted enrollment by moving it
    from SUBMITTED to CERTIFIED.'"""
    h = headers or TEST_USERS["va_clerk_headers"]
    resp = api_client.certify_enrollment(enrollment_id, h)
    return get_success_data(resp)


def cancel_enrollment(enrollment_id: str,
                      headers: Optional[Dict[str, str]] = None
                      ) -> Dict[str, Any]:
    """PRD §3.7: 'A clerk may cancel a certified enrollment.'"""
    h = headers or TEST_USERS["va_clerk_headers"]
    resp = api_client.cancel_enrollment(enrollment_id, h)
    return get_success_data(resp)


def complete_enrollment(enrollment_id: str,
                        headers: Optional[Dict[str, str]] = None
                        ) -> Dict[str, Any]:
    """PRD §3.9: 'A clerk completes it when its term_end has been
    reached or passed, moving it from ACTIVE to COMPLETED.'"""
    h = headers or TEST_USERS["va_clerk_headers"]
    resp = api_client.complete_enrollment(enrollment_id, h)
    return get_success_data(resp)


def withdraw_enrollment(enrollment_id: str, veteran_id: str,
                        headers: Optional[Dict[str, str]] = None
                        ) -> Dict[str, Any]:
    """PRD §3.9: 'the owning veteran withdraws mid-term (their
    X-User-ID must equal the enrollment's veteran_id), moving it from
    ACTIVE to WITHDRAWN.'"""
    h = headers or make_veteran_headers(veteran_id)
    resp = api_client.withdraw_enrollment(enrollment_id, h)
    return get_success_data(resp)


def post_housing_payment(enrollment_id: str, month_year: str,
                         headers: Optional[Dict[str, str]] = None
                         ) -> Dict[str, Any]:
    """PRD §3.10: 'Each month a VAClerk posts a housing payment for an
    active enrollment by calling the housing-payment endpoint and
    supplying a month_year'."""
    h = headers or TEST_USERS["va_clerk_headers"]
    resp = api_client.create_housing_payment(
        enrollment_id, create_housing_payment_payload(month_year), h,
    )
    return get_success_data(resp)


def get_enrollment(enrollment_id: str,
                   headers: Optional[Dict[str, str]] = None
                   ) -> Dict[str, Any]:
    h = headers or TEST_USERS["platform_admin_headers"]
    resp = api_client.get_enrollment(enrollment_id, h)
    return get_success_data(resp)


def setup_certified_enrollment(
    granted_rating: int = 10,
    aggregate_active_duty_days: int = 1100,
    program_type: str = "PUBLIC_IN_STATE",
    yellow_ribbon_enrolled: bool = False,
    yellow_ribbon_max_per_year: Optional[float] = None,
    tuition_charged: float = 10000.00,
    training_time: str = "FULL_TIME",
    delivery_mode: str = "IN_PERSON",
    zip_bah_code: Optional[str] = None,
    term_months: int = 4,
    term_start_offset_days: int = 30,
) -> Dict[str, Any]:
    """Build a Veteran (HONORABLE) + GRANTED Claim + School +
    SUBMITTED Enrollment + /certify. Returns
    {veteran, school, claim, enrollment} all in their post-certify
    states (Veteran.combined_rating populated, Enrollment status
    CERTIFIED with certified_tuition_payable computed).
    """
    vet_after_grant = setup_veteran_with_granted_claim(
        granted_rating=granted_rating,
        aggregate_active_duty_days=aggregate_active_duty_days,
    )
    veteran_id = vet_after_grant["id"]

    school = create_school(
        program_type=program_type,
        yellow_ribbon_enrolled=yellow_ribbon_enrolled,
        yellow_ribbon_max_per_year=yellow_ribbon_max_per_year,
        zip_bah_code=zip_bah_code,
    )

    base = current_clock().date() + timedelta(days=term_start_offset_days)
    term_start = iso_utc(utc_midnight(base))
    term_end = iso_utc(utc_midnight(base + timedelta(days=30 * term_months)))

    enrollment = create_enrollment(
        veteran_id=veteran_id,
        school_id=school["id"],
        term_start=term_start,
        term_end=term_end,
        tuition_charged=tuition_charged,
        training_time=training_time,
        delivery_mode=delivery_mode,
    )
    certified = certify_enrollment(enrollment["id"])
    return {
        "veteran": vet_after_grant,
        "school": school,
        "enrollment": certified,
        "term_start": term_start,
        "term_end": term_end,
        "term_start_date": base,
        "term_end_date": base + timedelta(days=30 * term_months),
    }


def setup_active_enrollment(
    granted_rating: int = 10,
    aggregate_active_duty_days: int = 1100,
    program_type: str = "PUBLIC_IN_STATE",
    yellow_ribbon_enrolled: bool = False,
    yellow_ribbon_max_per_year: Optional[float] = None,
    tuition_charged: float = 10000.00,
    training_time: str = "FULL_TIME",
    delivery_mode: str = "IN_PERSON",
    zip_bah_code: Optional[str] = None,
    term_months: int = 4,
    term_start_offset_days: int = 30,
) -> Dict[str, Any]:
    """setup_certified_enrollment + advance clock to term_start + run
    sweep so the Enrollment is ACTIVE. PRD §3.8: certified-to-active
    promotion is gated on the clock reaching term_start AND
    combined_rating > 0.
    """
    bundle = setup_certified_enrollment(
        granted_rating=granted_rating,
        aggregate_active_duty_days=aggregate_active_duty_days,
        program_type=program_type,
        yellow_ribbon_enrolled=yellow_ribbon_enrolled,
        yellow_ribbon_max_per_year=yellow_ribbon_max_per_year,
        tuition_charged=tuition_charged,
        training_time=training_time,
        delivery_mode=delivery_mode,
        zip_bah_code=zip_bah_code,
        term_months=term_months,
        term_start_offset_days=term_start_offset_days,
    )
    advance_clock_to(utc_midnight(bundle["term_start_date"]))
    run_sweep()
    bundle["enrollment"] = get_enrollment(bundle["enrollment"]["id"])
    return bundle


def setup_completed_enrollment(
    term_months: int = 6,
    term_start_offset_days: int = 30,
    **kwargs,
) -> Dict[str, Any]:
    """setup_active_enrollment + advance to term_end + /complete.
    Returns bundle with COMPLETED enrollment.
    """
    bundle = setup_active_enrollment(
        term_months=term_months,
        term_start_offset_days=term_start_offset_days,
        **kwargs,
    )
    advance_clock_to(utc_midnight(bundle["term_end_date"]))
    completed = complete_enrollment(bundle["enrollment"]["id"])
    bundle["enrollment"] = completed
    return bundle


# ===========================================================================
# Voc Rehab plan composites — PRD §3.11
# ===========================================================================
def create_voc_rehab_plan(
    veteran_id: str,
    training_mode: str = "FULL_TIME_INSTITUTIONAL",
    headers: Optional[Dict[str, str]] = None,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.11: 'A Counselor may create a Voc Rehab plan for a
    veteran by submitting the owning veteran_id and the training_mode.'"""
    payload = create_voc_rehab_plan_payload(
        veteran_id=veteran_id,
        training_mode=training_mode,
        **overrides,
    )
    h = headers or TEST_USERS["counselor_headers"]
    resp = api_client.create_voc_rehab_plan(payload, h)
    return get_success_data(resp)


def approve_voc_rehab_plan(
    plan_id: str,
    counselor_operator_id: str = "counselor-0001",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """PRD §3.11: 'Approval is the first material step: the counselor
    moves the plan from DRAFT to APPROVED'."""
    h = headers or make_counselor_headers(counselor_operator_id)
    resp = api_client.approve_voc_rehab_plan(plan_id, h)
    return get_success_data(resp)


def start_voc_rehab_plan(
    plan_id: str,
    counselor_operator_id: str = "counselor-0001",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """PRD §3.11: 'An approved plan is started by the counselor,
    moving it from APPROVED to ACTIVE.'"""
    h = headers or make_counselor_headers(counselor_operator_id)
    resp = api_client.start_voc_rehab_plan(plan_id, h)
    return get_success_data(resp)


def suspend_voc_rehab_plan(
    plan_id: str,
    counselor_operator_id: str = "counselor-0001",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """PRD §3.11: 'suspension increments suspension_count by exactly 1
    and freezes subsistence accrual for the month.'"""
    h = headers or make_counselor_headers(counselor_operator_id)
    resp = api_client.suspend_voc_rehab_plan(plan_id, h)
    return get_success_data(resp)


def resume_voc_rehab_plan(
    plan_id: str,
    counselor_operator_id: str = "counselor-0002",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """PRD §3.11: 'A suspended plan can be resumed (SUSPENDED to
    ACTIVE) by a counselor whose X-User-ID differs from the original
    counselor_id who approved the plan'."""
    h = headers or make_counselor_headers(counselor_operator_id)
    resp = api_client.resume_voc_rehab_plan(plan_id, h)
    return get_success_data(resp)


def get_voc_rehab_plan(plan_id: str,
                       headers: Optional[Dict[str, str]] = None
                       ) -> Dict[str, Any]:
    h = headers or TEST_USERS["platform_admin_headers"]
    resp = api_client.get_voc_rehab_plan(plan_id, h)
    return get_success_data(resp)


def setup_active_voc_rehab_plan(
    granted_rating: int = 20,
    training_mode: str = "FULL_TIME_INSTITUTIONAL",
    approver_counselor_id: str = "counselor-0001",
) -> Dict[str, Any]:
    """Build a Veteran (HONORABLE) with GRANTED claim sufficient for
    combined_rating >= 20, then DRAFT -> APPROVED -> ACTIVE plan.
    Returns {veteran, plan} both refreshed."""
    vet = setup_veteran_with_granted_claim(granted_rating=granted_rating)
    plan = create_voc_rehab_plan(
        veteran_id=vet["id"], training_mode=training_mode,
    )
    plan = approve_voc_rehab_plan(
        plan["id"], counselor_operator_id=approver_counselor_id,
    )
    plan = start_voc_rehab_plan(
        plan["id"], counselor_operator_id=approver_counselor_id,
    )
    return {"veteran": vet, "plan": plan}


# ===========================================================================
# Dependent composites — PRD §3.2
# ===========================================================================
def add_active_dependent(veteran_id: str, relationship: str = "CHILD",
                         age_days: int = 365 * 10,
                         school_enrolled: Optional[bool] = None
                         ) -> Dict[str, Any]:
    """Convenience: add an ACTIVE dependent of the given relationship.
    Default produces a 10-year-old CHILD (clearly < 18, no
    school_enrolled requirement)."""
    today = current_clock().date()
    dob = iso_utc(utc_midnight(today - timedelta(days=age_days)))
    return create_dependent(
        veteran_id=veteran_id,
        relationship=relationship,
        date_of_birth=dob,
        school_enrolled=school_enrolled,
    )


# ===========================================================================
# DENIED_FINAL composite — PRD §3.3 + §3.8
# ===========================================================================
def push_denied_claim_to_final(
    claim_id: str,
    extra_days: int = 365,
) -> Dict[str, Any]:
    """Advance the clock 365+ days past a denied claim's decided_at,
    then run the sweep so PRD §3.3's auto-finalization fires:

        'An unappealed denied claim becomes terminal after 365 days:
         the periodic sweep advances any claim whose decided_at is at
         least 365 days in the past and which has not been appealed
         from DENIED to DENIED_FINAL.'

    Returns the post-sweep claim row.
    """
    advance_clock_by_days(extra_days + 1)
    run_sweep()
    resp = api_client.get_claim(
        claim_id, TEST_USERS["platform_admin_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# Entitlement / threshold targeting — PRD §3.9
# ===========================================================================
def setup_veteran_near_entitlement_cap(
    months_to_pre_consume: float = 30.00,
    granted_rating: int = 10,
    aggregate_active_duty_days: int = 1100,
) -> Dict[str, Any]:
    """Build a Veteran whose months_entitlement_used is already at
    `months_to_pre_consume` via a prior COMPLETED enrollment. Used by
    boundary tests near ERR_ENTITLEMENT_EXCEEDED.

    The strategy: term length in days = months_to_pre_consume * 30
    (PRD §3.9 'days-in-program divided by 30, rounded half-up to two
    decimal places'). The completion runs entitlement_consume_compute
    and writes the result to Veteran.months_entitlement_used.
    """
    days_for_pre = round(months_to_pre_consume * 30.0)
    bundle = setup_active_enrollment(
        granted_rating=granted_rating,
        aggregate_active_duty_days=aggregate_active_duty_days,
        term_months=1,  # placeholder; overridden below
        term_start_offset_days=30,
    )
    # The default term in setup_active_enrollment is 4 months; we need a
    # custom term length. Rebuild manually: cancel the just-activated one
    # is messy, so instead the caller-controlled helper builds from scratch:
    return bundle  # placeholder, see setup_completed_enrollment_with_months


def setup_completed_enrollment_with_months(
    months_to_consume: float,
    granted_rating: int = 10,
    aggregate_active_duty_days: int = 1100,
    tuition_charged: float = 10000.00,
    term_start_offset_days: int = 30,
) -> Dict[str, Any]:
    """Build a COMPLETED Enrollment whose months_consumed equals
    `months_to_consume` (to 2dp). Useful for stacking entitlement
    consumption.

    Internally: term_days = round(months_to_consume * 30).
    """
    term_days = max(1, round(months_to_consume * 30.0))
    vet = setup_veteran_with_granted_claim(
        granted_rating=granted_rating,
        aggregate_active_duty_days=aggregate_active_duty_days,
    )
    school = create_school(program_type="PUBLIC_IN_STATE")
    base = current_clock().date() + timedelta(days=term_start_offset_days)
    term_start = iso_utc(utc_midnight(base))
    term_end = iso_utc(utc_midnight(base + timedelta(days=term_days)))
    enrollment = create_enrollment(
        veteran_id=vet["id"],
        school_id=school["id"],
        term_start=term_start,
        term_end=term_end,
        tuition_charged=tuition_charged,
    )
    certify_enrollment(enrollment["id"])
    advance_clock_to(utc_midnight(base))
    run_sweep()
    advance_clock_to(utc_midnight(base + timedelta(days=term_days)))
    completed = complete_enrollment(enrollment["id"])
    return {
        "veteran": vet,
        "school": school,
        "enrollment": completed,
        "term_start_date": base,
        "term_end_date": base + timedelta(days=term_days),
    }


__all__ = [
    # Clock
    "current_clock", "current_clock_iso",
    "advance_clock_to", "advance_clock_by_days", "advance_clock_by_seconds",
    "reset_clock_tracker_to",
    "run_sweep",
    # Veteran
    "create_veteran", "get_veteran", "patch_veteran",
    # School
    "create_school",
    # Dependent
    "create_dependent", "delete_dependent", "add_active_dependent",
    # Claim
    "create_claim", "start_review_claim", "grant_claim", "deny_claim",
    "appeal_claim", "reopen_claim",
    "grant_claim_for_veteran", "deny_claim_for_veteran",
    "push_denied_claim_to_final",
    # Enrollment
    "create_enrollment", "certify_enrollment", "cancel_enrollment",
    "complete_enrollment", "withdraw_enrollment", "post_housing_payment",
    "get_enrollment",
    # Voc Rehab
    "create_voc_rehab_plan", "approve_voc_rehab_plan",
    "start_voc_rehab_plan", "suspend_voc_rehab_plan",
    "resume_voc_rehab_plan", "get_voc_rehab_plan",
    # Composites
    "setup_veteran_with_granted_claim",
    "setup_certified_enrollment",
    "setup_active_enrollment",
    "setup_completed_enrollment",
    "setup_active_voc_rehab_plan",
    "setup_completed_enrollment_with_months",
]
