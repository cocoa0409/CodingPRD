"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared routes
only, and uses the lenient success validator so that a broken precondition
surfaces as a clear "Setup step failed" message.

Identity threading: an EstablishmentOperator's X-User-ID is the establishment's
own id and an Artist's X-User-ID is the artist's own id, so every
ownership-gated call below builds its headers from the real entity id.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    bbp_training_payload,
    create_artist_payload,
    create_complaint_payload,
    create_enforcement_action_payload,
    create_establishment_payload,
    create_infection_report_payload,
    create_inspection_payload,
    create_minor_consent_payload,
    create_plan_review_payload,
    create_procedure_log_payload,
    create_renewal_application_payload,
    create_sterilization_record_payload,
    create_violation_payload,
    plan_review_decision_payload,
)
from .test_users import (
    TEST_USERS,
    make_artist_headers,
    make_operator_headers,
)

HO = TEST_USERS["health_officer_headers"]
HO2 = TEST_USERS["health_officer_2_headers"]
INSP = TEST_USERS["inspector_headers"]
REVIEWER = TEST_USERS["plan_reviewer_headers"]
CLERK = TEST_USERS["records_clerk_headers"]
PUBLIC = TEST_USERS["public_user_headers"]


# ─── Logical clock ─────────────────────────────────────────────────────


def set_clock(to_iso8601: str, headers=None) -> dict:
    """Move the logical clock forward and return the sweep payload."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, headers or HO)
    )


# ─── Tier 1: single-entity creation ────────────────────────────────────


def register_establishment(**overrides) -> dict:
    """Register one establishment; it is born PENDING_PLAN_REVIEW."""
    return get_success_data(
        api_client.create_establishment(create_establishment_payload(**overrides), HO)
    )


def read_establishment(establishment_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_establishment(establishment_id, headers or HO)
    )


def establishment_version(establishment_id: str) -> int:
    return read_establishment(establishment_id)["version"]


def submit_plan_review(establishment_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_plan_review(
            create_plan_review_payload(establishment_id, **overrides),
            make_operator_headers(establishment_id),
        )
    )


def decide_plan_review(plan_review_id: str, decision: str, **overrides) -> dict:
    return get_success_data(
        api_client.decide_plan_review(
            plan_review_id, plan_review_decision_payload(decision, **overrides), REVIEWER
        )
    )


def approve_plan_review(establishment_id: str, **overrides) -> dict:
    """Submit plans that meet code and approve them, moving the premises to
    PENDING_INSPECTION."""
    review = submit_plan_review(establishment_id, **overrides)
    return decide_plan_review(review["id"], "APPROVE")


def schedule_inspection(
    establishment_id: str,
    inspection_type: str = "ROUTINE",
    scheduled_start_at: str = "2026-05-05T00:00:00Z",
    scheduled_end_at: str = "2026-05-05T02:00:00Z",
    headers=None,
) -> dict:
    return get_success_data(
        api_client.create_inspection(
            create_inspection_payload(
                establishment_id,
                inspection_type=inspection_type,
                scheduled_start_at=scheduled_start_at,
                scheduled_end_at=scheduled_end_at,
            ),
            headers or INSP,
        )
    )


def pass_preopening_inspection(establishment_id: str) -> dict:
    """Schedule, start and finalize a citation-free PREOPENING visit, which
    therefore lands in PASSED."""
    inspection = schedule_inspection(
        establishment_id,
        inspection_type="PREOPENING",
        scheduled_start_at=TEST_DEFAULTS["PREOPENING_START"],
        scheduled_end_at=TEST_DEFAULTS["PREOPENING_END"],
    )
    get_success_data(api_client.start_inspection(inspection["id"], INSP))
    return get_success_data(api_client.finalize_inspection(inspection["id"], INSP))


def activate_establishment(establishment_id: str) -> dict:
    return get_success_data(api_client.activate_establishment(establishment_id, HO))


# ─── Tier 2: the permitted-premises preamble ───────────────────────────


def create_permitted_establishment(**overrides) -> dict:
    """Full issuance path: register → plans approved → PREOPENING passed →
    permit issued. Returns the ACTIVE establishment."""
    establishment = register_establishment(**overrides)
    approve_plan_review(establishment["id"])
    pass_preopening_inspection(establishment["id"])
    return activate_establishment(establishment["id"])


def create_establishment_pending_inspection(**overrides) -> dict:
    """Register and approve the plans only; the premises stops at
    PENDING_INSPECTION."""
    establishment = register_establishment(**overrides)
    approve_plan_review(establishment["id"])
    return read_establishment(establishment["id"])


# ─── Tier 3: artists ───────────────────────────────────────────────────


def register_artist(establishment_id: str, legal_name: str = "Test Practitioner") -> dict:
    return get_success_data(
        api_client.create_artist(
            create_artist_payload(establishment_id, legal_name=legal_name),
            make_operator_headers(establishment_id),
        )
    )


def record_bbp_training(artist_id: str, completed_on: str = None) -> dict:
    return get_success_data(
        api_client.record_bbp_training(
            artist_id, bbp_training_payload(completed_on), make_artist_headers(artist_id)
        )
    )


def create_active_artist(
    establishment_id: str,
    legal_name: str = "Test Practitioner",
    completed_on: str = None,
) -> dict:
    """Register a practitioner, record live training and permit them."""
    artist = register_artist(establishment_id, legal_name)
    record_bbp_training(artist["id"], completed_on)
    return get_success_data(api_client.activate_artist(artist["id"], HO))


def read_artist(artist_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_artist(artist_id, headers or HO))


def create_permitted_establishment_with_artist(
    legal_name: str = "Test Practitioner", **overrides
):
    """ACTIVE premises with one ACTIVE practitioner. Returns (establishment, artist)."""
    establishment = create_permitted_establishment(**overrides)
    artist = create_active_artist(establishment["id"], legal_name)
    return establishment, artist


# ─── Tier 4: inspections in progress and violations ────────────────────


def start_inspection_at(
    establishment_id: str,
    scheduled_start_at: str,
    scheduled_end_at: str,
    inspection_type: str = "ROUTINE",
    advance_clock: bool = True,
) -> dict:
    """Book a visit, move the clock to its start instant and begin it."""
    inspection = schedule_inspection(
        establishment_id,
        inspection_type=inspection_type,
        scheduled_start_at=scheduled_start_at,
        scheduled_end_at=scheduled_end_at,
    )
    if advance_clock:
        set_clock(scheduled_start_at)
    return get_success_data(api_client.start_inspection(inspection["id"], INSP))


def cite_violation(
    inspection_id: str,
    violation_code: str = "STER_004",
    severity: str = "NONCRITICAL",
    narrative: str = "Autoclave log gap.",
) -> dict:
    return get_success_data(
        api_client.create_violation(
            inspection_id,
            create_violation_payload(violation_code, severity, narrative),
            INSP,
        )
    )


def finalize_inspection(inspection_id: str) -> dict:
    return get_success_data(api_client.finalize_inspection(inspection_id, INSP))


def create_open_violations(
    establishment_id: str,
    codes_and_severities,
    scheduled_start_at: str = "2026-05-05T00:00:00Z",
    scheduled_end_at: str = "2026-05-05T02:00:00Z",
    finalize: bool = False,
):
    """Start a ROUTINE visit and cite the supplied (code, severity) pairs.

    Returns (inspection, [violations]).
    """
    inspection = start_inspection_at(
        establishment_id, scheduled_start_at, scheduled_end_at
    )
    violations = [
        cite_violation(inspection["id"], code, severity, f"{code} observed.")
        for code, severity in codes_and_severities
    ]
    if finalize:
        inspection = finalize_inspection(inspection["id"])
    return inspection, violations


def submit_correction(violation_id: str, establishment_id: str, note: str) -> dict:
    return get_success_data(
        api_client.submit_violation_correction(
            violation_id,
            {"correction_note": note},
            make_operator_headers(establishment_id),
        )
    )


def decide_correction(violation_id: str, decision: str) -> dict:
    return get_success_data(
        api_client.decide_violation_correction(violation_id, {"decision": decision}, INSP)
    )


# ─── Tier 5: sterilization evidence ────────────────────────────────────


def file_sterilization_record(
    establishment_id: str,
    cycle_completed_at: str,
    spore_test_result: str = "PASS",
    supersedes_record_id: str = None,
    device_serial: str = "AC-1",
) -> dict:
    payload = create_sterilization_record_payload(
        establishment_id,
        cycle_completed_at=cycle_completed_at,
        spore_test_result=spore_test_result,
        device_serial=device_serial,
    )
    if supersedes_record_id is not None:
        payload["supersedes_record_id"] = supersedes_record_id
    return get_success_data(
        api_client.create_sterilization_record(
            payload, make_operator_headers(establishment_id)
        )
    )


def file_passing_spore_tests(establishment_id: str, dates) -> list:
    return [file_sterilization_record(establishment_id, d, "PASS") for d in dates]


def compliance_summary(establishment_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_compliance_summary(establishment_id, headers or HO)
    )


# ─── Tier 6: consents and procedure logs ───────────────────────────────


def file_minor_consent(establishment_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_minor_consent(
            create_minor_consent_payload(establishment_id, **overrides),
            make_operator_headers(establishment_id),
        )
    )


def create_verified_minor_consent(establishment_id: str, **overrides) -> dict:
    consent = file_minor_consent(establishment_id, **overrides)
    return get_success_data(
        api_client.verify_minor_consent(consent["id"], {"decision": "VERIFY"}, CLERK)
    )


def file_procedure_log(establishment_id: str, artist_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_procedure_log(
            create_procedure_log_payload(establishment_id, artist_id, **overrides),
            make_artist_headers(artist_id),
        )
    )


def audit_procedure_log(procedure_log_id: str, decision: str, finding_code: str = None) -> dict:
    payload = {"decision": decision}
    if finding_code is not None:
        payload["finding_code"] = finding_code
    return get_success_data(api_client.audit_procedure_log(procedure_log_id, payload, HO))


# ─── Tier 7: complaints and infection reports ──────────────────────────


def file_complaint(establishment_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_complaint(
            create_complaint_payload(establishment_id, **overrides), PUBLIC
        )
    )


def transition_complaint(complaint_id: str, action: str) -> dict:
    return get_success_data(
        api_client.transition_complaint(complaint_id, {"action": action}, HO)
    )


def file_infection_report(establishment_id: str, artist_id: str = None, **overrides) -> dict:
    payload = create_infection_report_payload(establishment_id, **overrides)
    if artist_id is not None:
        payload["artist_id"] = artist_id
    return get_success_data(api_client.create_infection_report(payload, PUBLIC))


def advance_investigation(infection_report_id: str, action: str) -> dict:
    return get_success_data(
        api_client.advance_infection_investigation(
            infection_report_id, {"action": action}, HO
        )
    )


def advance_notification(infection_report_id: str, action: str) -> dict:
    return get_success_data(
        api_client.advance_infection_notification(
            infection_report_id, {"action": action}, HO
        )
    )


def create_screening_infection_report(establishment_id: str, artist_id: str = None, **overrides):
    """File a report and move its investigation axis to SCREENING."""
    report = file_infection_report(establishment_id, artist_id, **overrides)
    advance_investigation(report["id"], "SCREEN")
    return report


# ─── Tier 8: enforcement ───────────────────────────────────────────────


def issue_establishment_enforcement(
    establishment_id: str,
    action_type: str = "SUSPENSION",
    reason_code: str = "IMMINENT_HEALTH_HAZARD",
    officer_headers=None,
) -> dict:
    return get_success_data(
        api_client.create_establishment_enforcement_action(
            establishment_id,
            create_enforcement_action_payload(action_type, reason_code),
            officer_headers or HO,
        )
    )


def issue_artist_enforcement(
    artist_id: str,
    expected_artist_version: int,
    action_type: str = "SUSPENSION",
    reason_code: str = "UNLICENSED_PRACTICE",
    officer_headers=None,
) -> dict:
    payload = create_enforcement_action_payload(action_type, reason_code)
    payload["expected_artist_version"] = expected_artist_version
    return get_success_data(
        api_client.create_artist_enforcement_action(
            artist_id, payload, officer_headers or HO
        )
    )


def lift_enforcement(enforcement_action_id: str, officer_headers=None) -> dict:
    return get_success_data(
        api_client.lift_enforcement_action(enforcement_action_id, officer_headers or HO2)
    )


# ─── Tier 9: renewals and money ────────────────────────────────────────


def open_renewal_application(establishment_id: str, **overrides) -> dict:
    """Read the establishment's current version and open a DRAFT application."""
    version = establishment_version(establishment_id)
    return get_success_data(
        api_client.create_renewal_application(
            create_renewal_application_payload(establishment_id, version, **overrides),
            make_operator_headers(establishment_id),
        )
    )


def submit_renewal_application(renewal_application_id: str, establishment_id: str) -> dict:
    return get_success_data(
        api_client.submit_renewal_application(
            renewal_application_id, make_operator_headers(establishment_id)
        )
    )


def pay_renewal_application(renewal_application_id: str, amount_cents: int) -> dict:
    return get_success_data(
        api_client.pay_renewal_application(
            renewal_application_id, {"amount_cents": amount_cents}, CLERK
        )
    )


def create_submitted_renewal(establishment_id: str, **overrides) -> dict:
    """Open and submit a renewal application; returns the SUBMITTED application."""
    application = open_renewal_application(establishment_id, **overrides)
    return submit_renewal_application(application["id"], establishment_id)


def create_paid_renewal(establishment_id: str, **overrides) -> dict:
    """Open, submit and settle a renewal application in full."""
    application = create_submitted_renewal(establishment_id, **overrides)
    return pay_renewal_application(application["id"], application["fee_estimate_cents"])


def review_renewal_application(renewal_application_id: str, decision: str, **extra) -> dict:
    payload = {"decision": decision}
    payload.update(extra)
    return get_success_data(
        api_client.review_renewal_application(renewal_application_id, payload, HO)
    )


def refund_renewal_application(renewal_application_id: str) -> dict:
    return get_success_data(
        api_client.refund_renewal_application(renewal_application_id, CLERK)
    )
