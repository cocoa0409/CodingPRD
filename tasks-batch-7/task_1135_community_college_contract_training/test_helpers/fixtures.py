"""Composite setup helpers.

Every fixture builds preconditions from scratch using only PRD-declared
endpoints; each test starts against an empty database. Setup calls use the
lenient get_success_data() validator so setup failures surface as clear
"Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_employer_payload,
    create_needs_assessment_payload,
    create_training_agreement_payload,
    create_grant_program_payload,
    create_instructor_payload,
    create_venue_payload,
    create_cohort_payload,
    create_session_payload,
    create_participant_payload,
)
from .test_users import (
    TEST_USERS,
    make_employer_contact_headers,
    make_instructor_headers,
)

ADMIN = TEST_USERS["admin_headers"]
COORD = TEST_USERS["coordinator_headers"]
CRED = TEST_USERS["credential_officer_headers"]
GRANT = TEST_USERS["grant_officer_headers"]
BILL = TEST_USERS["billing_clerk_headers"]


def _ok(resp, label):
    data = get_success_data(resp)
    assert data is not None, f"Setup failed: {label}"
    return data


# ---------------------------------------------------------------------------
# Tier 1/2: employer + assessment + agreement chains
# ---------------------------------------------------------------------------

def create_employer(**overrides):
    return _ok(api_client.create_employer(create_employer_payload(**overrides), COORD), "create_employer")


def create_approved_assessment(employer_id, curriculum_modules=None):
    payload = create_needs_assessment_payload()
    if curriculum_modules is not None:
        payload["curriculum_modules"] = curriculum_modules
    na = _ok(api_client.create_needs_assessment(employer_id, payload, COORD), "create_needs_assessment")
    _ok(api_client.submit_needs_assessment(na["id"], COORD), "submit_needs_assessment")
    na = _ok(api_client.approve_needs_assessment(na["id"], ADMIN), "approve_needs_assessment")
    return na


def create_agreement(employer_id, assessment_id, **overrides):
    return _ok(
        api_client.create_training_agreement(
            employer_id, create_training_agreement_payload(assessment_id, **overrides), COORD
        ),
        "create_training_agreement",
    )


def create_quoted_agreement(employer_id, assessment_id, **overrides):
    agr = create_agreement(employer_id, assessment_id, **overrides)
    return _ok(api_client.quote_training_agreement(agr["id"], COORD), "quote_training_agreement")


def create_signed_agreement(employer_id, assessment_id, **overrides):
    agr = create_quoted_agreement(employer_id, assessment_id, **overrides)
    return _ok(
        api_client.sign_training_agreement(agr["id"], make_employer_contact_headers(employer_id)),
        "sign_training_agreement",
    )


def setup_employer_with_approved_assessment(employer_overrides=None, curriculum_modules=None):
    emp = create_employer(**(employer_overrides or {}))
    na = create_approved_assessment(emp["id"], curriculum_modules=curriculum_modules)
    return emp, na


def setup_signed_agreement(agreement_overrides=None, curriculum_modules=None, employer_overrides=None):
    """Employer + APPROVED assessment + SIGNED agreement. Returns (emp, na, agr)."""
    emp, na = setup_employer_with_approved_assessment(
        employer_overrides=employer_overrides, curriculum_modules=curriculum_modules
    )
    agr = create_signed_agreement(emp["id"], na["id"], **(agreement_overrides or {}))
    return emp, na, agr


# ---------------------------------------------------------------------------
# Tier 2/3: cohort / session / instructor hierarchy
# ---------------------------------------------------------------------------

def create_venue_for_mode(delivery_mode, **overrides):
    kind = "CAMPUS_LAB" if delivery_mode == "ON_CAMPUS" else "EMPLOYER_SITE"
    overrides.setdefault("kind", kind)
    return _ok(api_client.create_venue(create_venue_payload(**overrides), ADMIN), "create_venue")


def create_cohort_under(agreement_id, **overrides):
    return _ok(
        api_client.create_cohort(agreement_id, create_cohort_payload(**overrides), COORD),
        "create_cohort",
    )


def create_session_on(cohort_id, venue_id, start_at, end_at):
    return _ok(
        api_client.create_session(
            cohort_id, create_session_payload(venue_id, start_at=start_at, end_at=end_at), COORD
        ),
        "create_session",
    )


def create_instructor(**overrides):
    return _ok(api_client.create_instructor(create_instructor_payload(**overrides), ADMIN), "create_instructor")


def propose_assignment(session_id, instructor_id, proposer_headers=None):
    return _ok(
        api_client.create_instructor_assignment(
            session_id, {"instructor_id": instructor_id}, proposer_headers or COORD
        ),
        "propose_assignment",
    )


def confirm_assignment(assignment_id, confirmer_headers=None):
    return _ok(
        api_client.confirm_instructor_assignment(assignment_id, confirmer_headers or CRED),
        "confirm_assignment",
    )


def propose_and_confirm(session_id, instructor_id, proposer_headers=None, confirmer_headers=None):
    asg = propose_assignment(session_id, instructor_id, proposer_headers=proposer_headers)
    confirm_assignment(asg["id"], confirmer_headers=confirmer_headers)
    return _ok(api_client.get_instructor_assignment(asg["id"], COORD), "get_instructor_assignment")


def enroll_participants(cohort_id, refs):
    out = []
    for ref in refs:
        out.append(
            _ok(
                api_client.create_participant(cohort_id, create_participant_payload(ref), COORD),
                "create_participant",
            )
        )
    return out


def setup_launchable_cohort(
    num_participants=1,
    sessions=(( "2026-06-15T09:00:00Z", "2026-06-15T11:00:00Z" ),),
    min_enrollment=1,
    agreement_overrides=None,
    curriculum_modules=None,
    instructor_overrides=None,
    venue_overrides=None,
    participant_prefix="P",
):
    """SIGNED agreement + SCHEDULED cohort with `sessions` PLANNED sessions,
    each holding a CONFIRMED assignment of one instructor, and
    `num_participants` ENROLLED participants. Returns a dict of ids/objects.
    """
    emp, na, agr = setup_signed_agreement(
        agreement_overrides=agreement_overrides, curriculum_modules=curriculum_modules
    )
    delivery_mode = (agreement_overrides or {}).get("delivery_mode", "ON_SITE")
    ven = create_venue_for_mode(delivery_mode, **(venue_overrides or {}))
    coh = create_cohort_under(
        agr["id"],
        delivery_mode=delivery_mode,
        min_enrollment=min_enrollment,
        start_date=(agreement_overrides or {}).get("cohort_start_date", "2026-06-15T00:00:00Z"),
        end_date=(agreement_overrides or {}).get("cohort_end_date", "2026-06-20T00:00:00Z"),
        venue_id=ven["id"],
    )
    ins = create_instructor(**(instructor_overrides or {}))
    session_ids = []
    for start_at, end_at in sessions:
        s = create_session_on(coh["id"], ven["id"], start_at, end_at)
        propose_and_confirm(s["id"], ins["id"])
        session_ids.append(s["id"])
    refs = [f"{participant_prefix}{i:02d}" for i in range(1, num_participants + 1)]
    participants = enroll_participants(coh["id"], refs)
    return {
        "employer": emp,
        "assessment": na,
        "agreement": agr,
        "venue": ven,
        "cohort": coh,
        "instructor": ins,
        "session_ids": session_ids,
        "participants": participants,
        "participant_refs": refs,
    }


def launch_cohort(cohort_id):
    return _ok(api_client.launch_cohort(cohort_id, COORD), "launch_cohort")


def close_session_attendance(session_id, instructor_id, attendance):
    """attendance: list of {external_employee_ref, attended_hours}."""
    return _ok(
        api_client.close_attendance(
            session_id, {"attendance": attendance}, make_instructor_headers(instructor_id)
        ),
        "close_attendance",
    )


def setup_launched_cohort(**kwargs):
    ctx = setup_launchable_cohort(**kwargs)
    ctx["cohort"] = launch_cohort(ctx["cohort"]["id"])
    return ctx


def setup_delivered_cohort(attendance_map=None, **kwargs):
    """Launched cohort then close_attendance on every session so the cohort
    reaches DELIVERED. attendance_map: {session_index: {ref: hours}} — defaults
    to full attendance for every enrolled participant on every session.
    """
    ctx = setup_launched_cohort(**kwargs)
    refs = ctx["participant_refs"]
    for idx, sid in enumerate(ctx["session_ids"]):
        if attendance_map and idx in attendance_map:
            entries = [
                {"external_employee_ref": ref, "attended_hours": h}
                for ref, h in attendance_map[idx].items()
            ]
        else:
            entries = [{"external_employee_ref": ref, "attended_hours": 2} for ref in refs]
        close_session_attendance(sid, ctx["instructor"]["id"], entries)
    ctx["cohort"] = _ok(api_client.get_cohort(ctx["cohort"]["id"], COORD), "get_cohort")
    return ctx


def setup_credentialed_cohort(**kwargs):
    ctx = setup_delivered_cohort(**kwargs)
    _ok(api_client.issue_credentials(ctx["cohort"]["id"], CRED), "issue_credentials")
    ctx["cohort"] = _ok(api_client.get_cohort(ctx["cohort"]["id"], COORD), "get_cohort")
    return ctx


# ---------------------------------------------------------------------------
# Grant helpers
# ---------------------------------------------------------------------------

def create_grant_program(**overrides):
    return _ok(
        api_client.create_grant_program(create_grant_program_payload(**overrides), ADMIN),
        "create_grant_program",
    )


def create_grant_application_for_cohort(cohort_id, program_id, requested_cents):
    coh = _ok(api_client.get_cohort(cohort_id, COORD), "get_cohort for OCC version")
    return _ok(
        api_client.create_grant_application(
            cohort_id,
            {
                "program_id": program_id,
                "requested_cents": requested_cents,
                "expected_cohort_version": coh["version"],
            },
            COORD,
        ),
        "create_grant_application",
    )


def submit_and_review(application_id):
    _ok(api_client.submit_grant_application(application_id, COORD), "submit_grant_application")
    _ok(api_client.start_review_grant_application(application_id, GRANT), "start_review")
    return _ok(api_client.get_grant_application(application_id, COORD), "get_grant_application")


def approve_application(application_id):
    _ok(api_client.approve_grant_application(application_id, GRANT), "approve_grant_application")
    return _ok(api_client.get_grant_application(application_id, COORD), "get_grant_application")


# ---------------------------------------------------------------------------
# Invoice helpers
# ---------------------------------------------------------------------------

def create_invoice_for_cohort(cohort_id, variant):
    return _ok(
        api_client.create_invoice(cohort_id, {"variant": variant}, BILL),
        "create_invoice",
    )
