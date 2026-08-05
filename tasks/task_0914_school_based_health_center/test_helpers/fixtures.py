"""Composite setup helpers.

Every test starts against an empty database, so each helper here builds its
preconditions from scratch using only endpoints the PRD declares. Setup calls
use the lenient validator so a broken precondition reads as "Setup step
failed" rather than as a confusing assertion deep inside a test.
"""

import itertools

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    clinician_payload,
    consent_payload,
    dose_payload,
    enrollment_payload,
    financial_profile_payload,
    guardian_payload,
    referral_payload,
    school_payload,
    screening_payload,
    student_payload,
    telehealth_session_payload,
    visit_payload,
)
from .test_users import (
    ADMIN,
    BILLING,
    CARE_COORDINATOR,
    REGISTRAR,
    make_clinician_headers,
    make_guardian_headers,
    make_student_headers,
)

DEFAULT_CLOCK = TEST_DEFAULTS["CLOCK"]
EARLY_CLOCK = TEST_DEFAULTS["EARLY_CLOCK"]
SPORTS_CLOCK = TEST_DEFAULTS["SPORTS_CLOCK"]
CURRENT_SCHOOL_YEAR = "2025-2026"


# ─── Tier 0: single-call primitives ─────────────────────────────────────────


def set_clock(to_iso8601: str) -> dict:
    """Move the logical clock. Mutates no entity."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def run_daily_sweep() -> dict:
    return get_success_data(api_client.daily_sweep(ADMIN))


_site_code_seq = itertools.count(1)


def create_school(**overrides) -> dict:
    """`site_code` must be unique across all school rows, so a fixture that is
    called twice inside one test mints a fresh code unless the caller pins one."""
    overrides.setdefault("site_code", f"LHS{next(_site_code_seq):04d}")
    return get_success_data(api_client.create_school(school_payload(**overrides), ADMIN))


def get_school(school_id: str) -> dict:
    return get_success_data(api_client.get_school(school_id, ADMIN))


def school_booked_minutes(school_id: str) -> int:
    return get_school(school_id)["telehealth_booked_minutes_total"]


def suspend_school(school_id: str) -> dict:
    return get_success_data(
        api_client.set_school_program_status(school_id, {"program_status": "SUSPENDED"}, ADMIN)
    )


def reinstate_school(school_id: str) -> dict:
    return get_success_data(
        api_client.set_school_program_status(school_id, {"program_status": "ACTIVE"}, ADMIN)
    )


def create_clinician(**overrides) -> dict:
    return get_success_data(api_client.create_clinician(clinician_payload(**overrides), ADMIN))


def create_student(**overrides) -> dict:
    return get_success_data(api_client.create_student(student_payload(**overrides), REGISTRAR))


def get_student(student_id: str) -> dict:
    return get_success_data(api_client.get_student(student_id, REGISTRAR))


def student_version(student_id: str) -> int:
    return get_student(student_id)["version"]


def set_financial_profile(student_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.update_financial_profile(
            student_id, financial_profile_payload(**overrides), REGISTRAR
        )
    )


def set_exemption(student_id: str, exemption_type: str) -> dict:
    return get_success_data(
        api_client.set_immunization_exemption(
            student_id, {"exemption_type": exemption_type}, REGISTRAR
        )
    )


def add_guardian(student_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.add_guardian(student_id, guardian_payload(**overrides), REGISTRAR)
    )


def set_guardian_opt_out(guardian_id: str, opted_out: bool) -> dict:
    """Flipped by the guardian themself, so identity is threaded through."""
    return get_success_data(
        api_client.set_notification_preference(
            guardian_id,
            {"notification_opt_out": opted_out},
            make_guardian_headers(guardian_id),
        )
    )


def create_enrollment(student_id: str, school_id: str, school_year=CURRENT_SCHOOL_YEAR) -> dict:
    """Re-reads the student so the optimistic-concurrency token is current."""
    version = student_version(student_id)
    return get_success_data(
        api_client.create_enrollment(
            student_id, enrollment_payload(school_id, version, school_year), REGISTRAR
        )
    )


def activate_enrollment(enrollment_id: str) -> dict:
    return get_success_data(api_client.activate_enrollment(enrollment_id, REGISTRAR))


def withdraw_enrollment(enrollment_id: str, reason="Family moved out of district") -> dict:
    return get_success_data(
        api_client.withdraw_enrollment(enrollment_id, {"reason": reason}, REGISTRAR)
    )


def reinstate_enrollment(enrollment_id: str) -> dict:
    return get_success_data(api_client.reinstate_enrollment(enrollment_id, REGISTRAR))


def get_enrollment(enrollment_id: str) -> dict:
    return get_success_data(api_client.get_enrollment(enrollment_id, REGISTRAR))


def grant_consent(
    student_id: str,
    category: str,
    granted_by_user_id: str,
    granted_by="GUARDIAN",
    school_year=CURRENT_SCHOOL_YEAR,
) -> dict:
    """Re-reads the student so the optimistic-concurrency token is current.
    A student-granted consent is sent under the student's own identity."""
    version = student_version(student_id)
    headers = REGISTRAR if granted_by == "GUARDIAN" else make_student_headers(student_id)
    return get_success_data(
        api_client.create_consent(
            student_id,
            consent_payload(category, granted_by_user_id, version, granted_by, school_year),
            headers,
        )
    )


def revoke_consent(consent_id: str, reason="Guardian withdrew consent") -> dict:
    return get_success_data(api_client.revoke_consent(consent_id, {"reason": reason}, REGISTRAR))


def get_consent_list(student_id: str, params=None) -> list:
    body = api_client.list_consents(student_id, REGISTRAR, params=params)
    return get_success_data(body)


def schedule_visit(student_id, school_id, clinician_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_visit(
            visit_payload(student_id, school_id, clinician_id, **overrides),
            make_clinician_headers(clinician_id),
        )
    )


def start_visit(visit_id: str, clinician_id: str) -> dict:
    return get_success_data(api_client.start_visit(visit_id, make_clinician_headers(clinician_id)))


def complete_visit(visit_id, clinician_id, disposition="TREATED_RETURNED_TO_CLASS") -> dict:
    return get_success_data(
        api_client.complete_visit(
            visit_id, {"disposition": disposition}, make_clinician_headers(clinician_id)
        )
    )


def get_visit(visit_id: str) -> dict:
    return get_success_data(api_client.get_visit(visit_id, REGISTRAR))


def record_dose(student_id, clinician_id, series_code, dose_number, administered_date, **overrides):
    return get_success_data(
        api_client.create_immunization_dose(
            student_id,
            dose_payload(series_code, dose_number, administered_date, **overrides),
            make_clinician_headers(clinician_id),
        )
    )


def void_dose(dose_id, clinician_id, reason="Recorded against the wrong student") -> dict:
    return get_success_data(
        api_client.void_immunization_dose(
            dose_id, {"reason": reason}, make_clinician_headers(clinician_id)
        )
    )


def get_dose(dose_id: str) -> dict:
    return get_success_data(api_client.get_immunization_dose(dose_id, REGISTRAR))


def record_screening(visit_id, clinician_id, instrument, numeric_result) -> dict:
    return get_success_data(
        api_client.create_screening(
            visit_id,
            screening_payload(instrument, numeric_result),
            make_clinician_headers(clinician_id),
        )
    )


def raise_referral(student_id, clinician_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_referral(
            student_id, referral_payload(**overrides), make_clinician_headers(clinician_id)
        )
    )


def log_outreach(referral_id: str, outcome: str, headers=None) -> dict:
    return get_success_data(
        api_client.log_outreach_attempt(referral_id, {"outcome": outcome}, headers or CARE_COORDINATOR)
    )


def report_back(referral_id, report_summary, report_received_date) -> dict:
    return get_success_data(
        api_client.report_back_referral(
            referral_id,
            {"report_summary": report_summary, "report_received_date": report_received_date},
            CARE_COORDINATOR,
        )
    )


def close_referral(referral_id, closure_note="Loop closed", headers=None) -> dict:
    return get_success_data(
        api_client.close_referral(
            referral_id, {"closure_note": closure_note}, headers or CARE_COORDINATOR
        )
    )


def get_referral(referral_id: str) -> dict:
    return get_success_data(api_client.get_referral(referral_id, CARE_COORDINATOR))


def record_clearance(visit_id, clinician_id, outcome, **overrides) -> dict:
    """Re-reads the student version through the visit, so the optimistic
    concurrency token travels correctly."""
    visit = get_visit(visit_id)
    payload = {"outcome": outcome, "expected_student_version": student_version(visit["student_id"])}
    payload.update(overrides)
    return get_success_data(
        api_client.create_sports_clearance(visit_id, payload, make_clinician_headers(clinician_id))
    )


def reevaluate_clearance(clearance_id, clinician_id, outcome, **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return get_success_data(
        api_client.reevaluate_sports_clearance(
            clearance_id, payload, make_clinician_headers(clinician_id)
        )
    )


def get_clearance(clearance_id: str) -> dict:
    return get_success_data(api_client.get_sports_clearance(clearance_id, REGISTRAR))


def book_session(visit_id, clinician_id, start_at, end_at) -> dict:
    return get_success_data(
        api_client.create_telehealth_session(
            telehealth_session_payload(visit_id, start_at, end_at),
            make_clinician_headers(clinician_id),
        )
    )


def complete_session(session_id, clinician_id) -> dict:
    return get_success_data(
        api_client.complete_telehealth_session(session_id, make_clinician_headers(clinician_id))
    )


def close_session(session_id, clinician_id, outcome, closure_reason=None) -> dict:
    payload = {"outcome": outcome}
    if closure_reason is not None:
        payload["closure_reason"] = closure_reason
    return get_success_data(
        api_client.close_telehealth_session(
            session_id, payload, make_clinician_headers(clinician_id)
        )
    )


def reschedule_session(session_id, clinician_id, start_at, end_at) -> dict:
    return get_success_data(
        api_client.reschedule_telehealth_session(
            session_id,
            {"start_at": start_at, "end_at": end_at},
            make_clinician_headers(clinician_id),
        )
    )


def get_session(session_id: str) -> dict:
    return get_success_data(api_client.get_telehealth_session(session_id, ADMIN))


def charges_for_visit(visit_id: str) -> list:
    return get_success_data(api_client.list_charges(BILLING, params={"visit_id": visit_id}))


def charge_of_category(visit_id: str, service_category: str) -> dict:
    rows = get_success_data(
        api_client.list_charges(
            BILLING, params={"visit_id": visit_id, "service_category": service_category}
        )
    )
    assert rows, f"Setup step failed: no {service_category} charge for visit {visit_id}"
    return rows[0]


def get_charge(charge_id: str) -> dict:
    return get_success_data(api_client.get_charge(charge_id, BILLING))


def submit_claim(charge_id: str) -> dict:
    return get_success_data(api_client.submit_claim(charge_id, BILLING))


def adjudicate(charge_id, outcome, payer_paid_amount_cents, denial_reason=None) -> dict:
    payload = {"outcome": outcome, "payer_paid_amount_cents": payer_paid_amount_cents}
    if denial_reason is not None:
        payload["denial_reason"] = denial_reason
    return get_success_data(api_client.adjudicate_charge(charge_id, payload, BILLING))


def appeal_charge(charge_id, appeal_note="Appeal with supporting documents") -> dict:
    return get_success_data(
        api_client.appeal_charge(charge_id, {"appeal_note": appeal_note}, BILLING)
    )


def notifications_for_visit(visit_id: str) -> list:
    return get_success_data(api_client.list_notifications(ADMIN, params={"visit_id": visit_id}))


def notifications_for_student(student_id: str, **filters) -> list:
    params = {"student_id": student_id}
    params.update(filters)
    return get_success_data(api_client.list_notifications(ADMIN, params=params))


def deliver_notification(notification_id: str, outcome: str) -> dict:
    return get_success_data(
        api_client.deliver_notification(notification_id, {"outcome": outcome}, ADMIN)
    )


def get_notification(notification_id: str) -> dict:
    return get_success_data(api_client.get_notification(notification_id, ADMIN))


def generate_report(period_start_date, period_end_date, **overrides) -> dict:
    payload = {"period_start_date": period_start_date, "period_end_date": period_end_date}
    payload.update(overrides)
    return get_success_data(api_client.create_report(payload, ADMIN))


# ─── Tier 1: a site and its clinical roster ─────────────────────────────────


def setup_site_and_clinician(clock=DEFAULT_CLOCK, capacity=1, discipline="MEDICAL") -> dict:
    """Logical clock at `clock`, one ACTIVE school, one clinician."""
    set_clock(clock)
    school = create_school(telehealth_concurrent_capacity=capacity)
    clinician = create_clinician(discipline=discipline)
    return {
        "school": school,
        "clinician": clinician,
        "clinician_headers": make_clinician_headers(clinician["id"]),
    }


DEFAULT_GUARDIANS = [
    {"full_name": "Mai Nguyen", "relationship": "MOTHER", "contact_email": "mai@example.org",
     "is_primary": True},
]


# ─── Tier 2: an enrolled student with consent on file ───────────────────────


def setup_enrolled_student(
    clock=DEFAULT_CLOCK,
    capacity=1,
    discipline="MEDICAL",
    dob=TEST_DEFAULTS["STUDENT_DOB"],
    first_name="Ava",
    last_name="Nguyen",
    financial=None,
    guardians=None,
    consents=("GENERAL_TREATMENT",),
    self_consent_categories=(),
    exemption=None,
    school_year=CURRENT_SCHOOL_YEAR,
    activate=True,
) -> dict:
    """The workhorse: an ACTIVE school, a clinician, a student with guardians,
    an ACTIVE enrollment for the current school year and the requested
    guardian-granted consents.

    Returns a dict with `school`, `clinician`, `student`, `guardians`,
    `guardian` (the first one, or None), `enrollment` and `consents`
    (category -> consent row).
    """
    ctx = setup_site_and_clinician(clock=clock, capacity=capacity, discipline=discipline)
    student = create_student(first_name=first_name, last_name=last_name, date_of_birth=dob)
    if financial is not None:
        student = set_financial_profile(student["id"], **financial)

    guardian_specs = DEFAULT_GUARDIANS if guardians is None else guardians
    guardian_rows = [add_guardian(student["id"], **spec) for spec in guardian_specs]

    if exemption is not None:
        student = set_exemption(student["id"], exemption)

    enrollment = create_enrollment(student["id"], ctx["school"]["id"], school_year)
    if activate:
        enrollment = activate_enrollment(enrollment["id"])

    consent_rows = {}
    for category in consents:
        assert guardian_rows, "A guardian-granted consent needs a guardian on file"
        consent_rows[category] = grant_consent(
            student["id"], category, guardian_rows[0]["id"], "GUARDIAN", school_year
        )
    for category in self_consent_categories:
        consent_rows[category] = grant_consent(
            student["id"], category, student["id"], "STUDENT_SELF", school_year
        )

    ctx.update(
        {
            "student": get_student(student["id"]),
            "guardians": guardian_rows,
            "guardian": guardian_rows[0] if guardian_rows else None,
            "enrollment": enrollment,
            "consents": consent_rows,
        }
    )
    return ctx


def setup_telehealth_enrolled_student(clock=EARLY_CLOCK, capacity=1, **overrides) -> dict:
    """An enrolled student carrying both a GENERAL_TREATMENT and a TELEHEALTH
    consent, which is what a telehealth encounter needs."""
    overrides.setdefault("consents", ("GENERAL_TREATMENT", "TELEHEALTH"))
    return setup_enrolled_student(clock=clock, capacity=capacity, **overrides)


# ─── Tier 3: encounters at a chosen point in their lifecycle ────────────────


def setup_visit_scheduled(ctx=None, visit_type="ACUTE", **visit_overrides) -> dict:
    """Adds one SCHEDULED encounter to an enrolled-student context."""
    ctx = ctx or setup_enrolled_student()
    visit = schedule_visit(
        ctx["student"]["id"],
        ctx["school"]["id"],
        ctx["clinician"]["id"],
        visit_type=visit_type,
        **visit_overrides,
    )
    ctx["visit"] = visit
    return ctx


def setup_visit_in_progress(ctx=None, visit_type="ACUTE", **visit_overrides) -> dict:
    ctx = setup_visit_scheduled(ctx, visit_type=visit_type, **visit_overrides)
    ctx["visit"] = start_visit(ctx["visit"]["id"], ctx["clinician"]["id"])
    return ctx


def setup_visit_completed(
    ctx=None, visit_type="ACUTE", disposition="TREATED_RETURNED_TO_CLASS", **visit_overrides
) -> dict:
    ctx = setup_visit_in_progress(ctx, visit_type=visit_type, **visit_overrides)
    ctx["visit"] = complete_visit(ctx["visit"]["id"], ctx["clinician"]["id"], disposition)
    ctx["charges"] = charges_for_visit(ctx["visit"]["id"])
    return ctx


# ─── Tier 4: charge lifecycle shortcuts ─────────────────────────────────────


def setup_pending_charge(financial=None, **overrides) -> dict:
    """A completed ACUTE encounter carrying exactly one PENDING charge.
    Returns the enrolled-student context plus `visit` and `charge`."""
    if financial is None:
        financial = {
            "household_income_annual_cents": TEST_DEFAULTS["TIER_A_INCOME_CENTS"],
            "household_size": TEST_DEFAULTS["TIER_A_HOUSEHOLD_SIZE"],
            "payer_route": "SELF_PAY",
        }
    ctx = setup_enrolled_student(financial=financial, **overrides)
    ctx = setup_visit_completed(ctx)
    ctx["charge"] = charge_of_category(ctx["visit"]["id"], "ACUTE_OFFICE_VISIT")
    return ctx


def setup_private_insurance_pending_charge(**overrides) -> dict:
    """The 151.66% / TIER_C private-insurance family the money rules use."""
    return setup_pending_charge(
        financial={
            "household_income_annual_cents": TEST_DEFAULTS["TIER_C_INCOME_CENTS"],
            "household_size": TEST_DEFAULTS["TIER_C_HOUSEHOLD_SIZE"],
            "payer_route": "PRIVATE_INSURANCE",
            "insurance_member_id": "PI-778",
        },
        first_name="Ben",
        last_name="Ortiz",
        guardians=[
            {"full_name": "Rosa Ortiz", "relationship": "MOTHER",
             "contact_email": "rosa@example.org", "is_primary": True}
        ],
        **overrides,
    )


def setup_denied_charge(**overrides) -> dict:
    """A private-insurance charge submitted as a claim and denied once."""
    ctx = setup_private_insurance_pending_charge(**overrides)
    submit_claim(ctx["charge"]["id"])
    adjudicate(ctx["charge"]["id"], "DENIED", 0, "Eligibility not on file")
    ctx["charge"] = get_charge(ctx["charge"]["id"])
    return ctx


# ─── Tier 4: immunization series and compliance targeting ───────────────────

# HEPB 1 on 2025-09-01, then the earliest dates the intervals permit once the
# 4-day grace is applied: dose 2 at +24 days, dose 3 at +52 days from dose 2.
FULL_SERIES_DATES = {
    "HEPB": {1: "2025-09-01", 2: "2025-09-25", 3: "2025-11-16"},
    "MMR": {1: "2025-10-01", 2: "2025-10-29"},
}


def setup_fully_immunized_student(clock=SPORTS_CLOCK, **overrides) -> dict:
    """An enrolled student carrying three VALID HEPB doses and two VALID MMR
    doses, which makes the compliance posture COMPLIANT with no exemption.
    Returns the context plus `doses` keyed "HEPB1", "HEPB2", …"""
    ctx = setup_enrolled_student(clock=clock, **overrides)
    doses = {}
    for series in ("HEPB", "MMR"):
        for number, administered in sorted(FULL_SERIES_DATES[series].items()):
            doses[f"{series}{number}"] = record_dose(
                ctx["student"]["id"], ctx["clinician"]["id"], series, number, administered
            )
    ctx["doses"] = doses
    ctx["student"] = get_student(ctx["student"]["id"])
    return ctx


# ─── Tier 4: sports-physical clearances ─────────────────────────────────────


def setup_sports_physical_in_progress(
    clock=SPORTS_CLOCK, exemption="MEDICAL", scheduled_start_at="2026-05-10T10:00:00Z", **overrides
) -> dict:
    """A SPORTS_PHYSICAL encounter in IN_PROGRESS for a student whose
    compliance posture already clears the immunization gate."""
    ctx = setup_enrolled_student(clock=clock, exemption=exemption, **overrides)
    return setup_visit_in_progress(
        ctx, visit_type="SPORTS_PHYSICAL", scheduled_start_at=scheduled_start_at
    )


def setup_active_clearance(outcome="CLEARED", **overrides) -> dict:
    """A SPORTS_PHYSICAL encounter carrying a live clearance."""
    ctx = setup_sports_physical_in_progress(**overrides)
    ctx["clearance"] = record_clearance(ctx["visit"]["id"], ctx["clinician"]["id"], outcome)
    return ctx


# ─── Tier 4: telehealth sessions ────────────────────────────────────────────


def setup_telehealth_visit(
    ctx=None, clock=EARLY_CLOCK, capacity=1, scheduled_start_at="2026-05-04T09:00:00Z", **overrides
) -> dict:
    """A TELEHEALTH ACUTE encounter in SCHEDULED, with both required consents
    on file."""
    ctx = ctx or setup_telehealth_enrolled_student(clock=clock, capacity=capacity, **overrides)
    return setup_visit_scheduled(
        ctx,
        visit_type="ACUTE",
        delivery_mode="TELEHEALTH",
        scheduled_start_at=scheduled_start_at,
    )


def add_telehealth_visit(ctx, clinician_id, scheduled_start_at) -> dict:
    """A second (or third) TELEHEALTH encounter in the same context, possibly
    for a different clinician."""
    return schedule_visit(
        ctx["student"]["id"],
        ctx["school"]["id"],
        clinician_id,
        visit_type="ACUTE",
        delivery_mode="TELEHEALTH",
        scheduled_start_at=scheduled_start_at,
    )


def setup_booked_session(
    clock=EARLY_CLOCK,
    capacity=1,
    start_at="2026-05-04T09:00:00Z",
    end_at="2026-05-04T09:30:00Z",
    **overrides,
) -> dict:
    """A TELEHEALTH encounter with one SCHEDULED session already booked."""
    ctx = setup_telehealth_visit(clock=clock, capacity=capacity, **overrides)
    ctx["session"] = book_session(
        ctx["visit"]["id"], ctx["clinician"]["id"], start_at, end_at
    )
    return ctx


# ─── Tier 4: referral loops ─────────────────────────────────────────────────


def setup_referral_open(clock=DEFAULT_CLOCK, **overrides) -> dict:
    """An enrolled student with one clinician-raised referral in OPEN."""
    ctx = setup_enrolled_student(clock=clock, **overrides)
    ctx["referral"] = raise_referral(ctx["student"]["id"], ctx["clinician"]["id"])
    return ctx


def setup_referral_outreach_in_progress(attempts=2, **overrides) -> dict:
    """A referral driven into OUTREACH_IN_PROGRESS by `attempts` NO_ANSWER
    logs, so `outreach_attempt_count` equals `attempts`."""
    ctx = setup_referral_open(**overrides)
    for _ in range(attempts):
        log_outreach(ctx["referral"]["id"], "NO_ANSWER")
    ctx["referral"] = get_referral(ctx["referral"]["id"])
    return ctx


def setup_referral_report_received(report_received_date="2026-05-04", **overrides) -> dict:
    """A referral walked to REPORT_RECEIVED, ready for loop closure."""
    ctx = setup_referral_open(**overrides)
    log_outreach(ctx["referral"]["id"], "REACHED")
    report_back(ctx["referral"]["id"], "Seen and treated", report_received_date)
    ctx["referral"] = get_referral(ctx["referral"]["id"])
    return ctx


# ─── Tier 5: notifications past the delivery boundary ───────────────────────


def setup_queued_visit_notification(**overrides) -> dict:
    """A completed ACUTE encounter whose VISIT_COMPLETED notification sits in
    QUEUED against the selected guardian."""
    ctx = setup_enrolled_student(**overrides)
    ctx = setup_visit_completed(ctx)
    rows = notifications_for_visit(ctx["visit"]["id"])
    assert rows, "Setup step failed: completing an encounter must raise a notification"
    ctx["notification"] = rows[0]
    return ctx


def setup_sent_visit_notification(**overrides) -> dict:
    """The same notification, delivered once so it sits in SENT."""
    ctx = setup_queued_visit_notification(**overrides)
    ctx["notification"] = deliver_notification(ctx["notification"]["id"], "DELIVERED")
    return ctx
