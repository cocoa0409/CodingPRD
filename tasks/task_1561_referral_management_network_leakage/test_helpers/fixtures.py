"""Composite setup helpers for multi-step test prerequisites.

Every test runs against a freshly restarted server with an empty database and
the logical clock at the startup default, so fixtures build their preconditions
from scratch using only PRD-declared endpoints. Setup calls use the lenient
get_success_data() so failures surface as clear "Setup step failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import DEFAULT_CLOCK_ISO
from .factories import (
    create_auth_rule_payload,
    create_insurance_plan_payload,
    create_participation_payload,
    create_patient_payload,
    create_referral_payload,
    create_referring_provider_payload,
    create_specialist_payload,
    book_appointment_payload,
    confirm_appointment_payload,
    consult_note_payload,
    document_patient_choice_payload,
    loop_closure_payload,
)
from .test_users import (
    TEST_USERS,
    make_referring_provider_headers,
    make_specialist_provider_headers,
    make_coordinator_headers,
    make_auditor_headers,
)

ADMIN = TEST_USERS["network_admin_headers"]
COORD = TEST_USERS["coordinator_headers"]
AUDIT = TEST_USERS["auditor_headers"]


# --- Primitive creators ------------------------------------------------------

def set_clock(to_iso8601: str):
    """Advance the logical clock (NetworkAdmin-only test-driving capability)."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    )


def create_plan(plan_code="PPO-1", payer_name="PayerOne", payer_mix_factor=1.0):
    return get_success_data(api_client.create_insurance_plan(
        create_insurance_plan_payload(
            plan_code=plan_code, payer_name=payer_name, payer_mix_factor=payer_mix_factor
        ),
        ADMIN,
    ))


def create_provider(name="Dr A", npi="2000000001", specialty="INTERNAL_MEDICINE"):
    return get_success_data(api_client.create_referring_provider(
        create_referring_provider_payload(name=name, npi=npi, specialty=specialty), ADMIN
    ))


def create_specialist(name="Dr Cardio", npi="1000000001", specialty="CARDIOLOGY",
                      base_region="NORTH", weekly_capacity=10, **overrides):
    return get_success_data(api_client.create_specialist(
        create_specialist_payload(
            name=name, npi=npi, specialty=specialty, base_region=base_region,
            weekly_capacity=weekly_capacity, **overrides,
        ),
        ADMIN,
    ))


def create_patient(plan_id, mrn="M001", full_name="Pat One", date_of_birth="1980-01-01",
                   region="NORTH"):
    return get_success_data(api_client.create_patient(
        create_patient_payload(
            plan_id, mrn=mrn, full_name=full_name, date_of_birth=date_of_birth, region=region
        ),
        ADMIN,
    ))


def create_participation(specialist_id, plan_id, tier="PREFERRED",
                         effective_from="2026-01-01", effective_to="2026-12-31"):
    return get_success_data(api_client.create_participation(
        create_participation_payload(
            specialist_id, plan_id, tier=tier,
            effective_from=effective_from, effective_to=effective_to,
        ),
        ADMIN,
    ))


def create_auth_rule(specialty, plan_id, requires_auth=True, auth_validity_days=10):
    return get_success_data(api_client.create_auth_rule(
        create_auth_rule_payload(
            specialty, plan_id, requires_auth=requires_auth,
            auth_validity_days=auth_validity_days,
        ),
        ADMIN,
    ))


# --- Tier 2: network hierarchy ----------------------------------------------

def setup_network(specialty="CARDIOLOGY", specialist_region="NORTH",
                  patient_region="NORTH", weekly_capacity=10, tier="PREFERRED",
                  effective_from="2026-01-01", effective_to="2026-12-31",
                  plan_code="PPO-1", payer_mix_factor=1.0,
                  specialist_overrides=None, with_participation=True,
                  provider_npi="2000000001", specialist_npi="1000000001",
                  patient_mrn="M001"):
    """Plan + specialist (+ participation window) + referring provider + patient.

    Returns a dict with keys: plan, specialist, provider, patient, participation.
    """
    plan = create_plan(plan_code=plan_code, payer_mix_factor=payer_mix_factor)
    specialist = create_specialist(
        npi=specialist_npi, specialty=specialty, base_region=specialist_region,
        weekly_capacity=weekly_capacity, **(specialist_overrides or {}),
    )
    participation = None
    if with_participation:
        participation = create_participation(
            specialist["id"], plan["id"], tier=tier,
            effective_from=effective_from, effective_to=effective_to,
        )
    provider = create_provider(npi=provider_npi)
    patient = create_patient(plan["id"], mrn=patient_mrn, region=patient_region)
    return {
        "plan": plan,
        "specialist": specialist,
        "provider": provider,
        "patient": patient,
        "participation": participation,
    }


# --- Tier 1/3: referral lifecycle progression --------------------------------

def create_referral(provider_id, patient_id, specialty="CARDIOLOGY",
                    diagnosis_code="I10", urgency="ROUTINE", **overrides):
    """Create a referral authored by the given provider (identity from X-User-ID)."""
    return get_success_data(api_client.create_referral(
        create_referral_payload(
            patient_id, specialty=specialty, diagnosis_code=diagnosis_code,
            urgency=urgency, **overrides,
        ),
        make_referring_provider_headers(provider_id),
    ))


def accept_referral(referral_id):
    return get_success_data(api_client.accept_referral(referral_id, COORD))


def get_referral(referral_id):
    return get_success_data(api_client.get_referral(referral_id, COORD))


def assign_specialist(referral_id, specialist_id):
    """Manual assignment; returns the updated referral (with its new version)."""
    return get_success_data(api_client.assign_specialist(
        referral_id, {"specialist_id": specialist_id}, COORD
    ))


def create_accepted_referral(provider_id, patient_id, **overrides):
    referral = create_referral(provider_id, patient_id, **overrides)
    return accept_referral(referral["id"])


def create_assigned_referral(provider_id, patient_id, specialist_id, **overrides):
    """Create + accept + assign. Returns the referral (version 3)."""
    referral = create_accepted_referral(provider_id, patient_id, **overrides)
    return assign_specialist(referral["id"], specialist_id)


def book_appointment(referral, scheduled_start, scheduled_end, specialist_id=None,
                     coordinator_user_id="coord-1"):
    """Book against the referral's current version. Returns the Appointment."""
    payload = book_appointment_payload(
        referral["version"], scheduled_start, scheduled_end,
        **({"specialist_id": specialist_id} if specialist_id else {}),
    )
    return get_success_data(api_client.book_appointment(
        referral["id"], payload, make_coordinator_headers(coordinator_user_id)
    ))


def create_booked_referral(provider_id, patient_id, specialist_id,
                           scheduled_start, scheduled_end,
                           coordinator_user_id="coord-1", **referral_overrides):
    """Create + accept + assign + book. Returns (referral_after_booking, appointment)."""
    referral = create_assigned_referral(
        provider_id, patient_id, specialist_id, **referral_overrides
    )
    appointment = book_appointment(
        referral, scheduled_start, scheduled_end,
        coordinator_user_id=coordinator_user_id,
    )
    return get_referral(referral["id"]), appointment


def confirm_appointment(appointment_id, channel="PHONE"):
    return get_success_data(api_client.confirm_appointment(
        appointment_id, confirm_appointment_payload(channel), COORD
    ))


def complete_appointment(appointment_id, specialist_id):
    """Complete as the owning specialist (entity-backed identity)."""
    return get_success_data(api_client.complete_appointment(
        appointment_id, make_specialist_provider_headers(specialist_id)
    ))


def mark_no_show(appointment_id):
    return get_success_data(api_client.mark_no_show(appointment_id, COORD))


def excuse_appointment(appointment_id, reason="Patient called ahead"):
    return get_success_data(api_client.excuse_appointment(
        appointment_id, {"reason": reason}, COORD
    ))


def cancel_appointment(appointment_id):
    return get_success_data(api_client.cancel_appointment(appointment_id, COORD))


def submit_consult_note(appointment_id, specialist_id, findings_summary="OK",
                        follow_up_recommended=False):
    """Submit a consult note as the owning specialist. Returns the ConsultNote."""
    return get_success_data(api_client.create_consult_note(
        appointment_id,
        consult_note_payload(
            findings_summary=findings_summary, follow_up_recommended=follow_up_recommended
        ),
        make_specialist_provider_headers(specialist_id),
    ))


def create_completed_referral(provider_id, patient_id, specialist_id,
                              scheduled_start, scheduled_end, complete_at=None,
                              coordinator_user_id="coord-1", **referral_overrides):
    """Booked + confirmed + completed. Returns (referral, appointment).

    The logical clock is advanced to ``complete_at`` (default: scheduled_start)
    before completion so the completion-time rule now >= scheduled_start holds.
    """
    referral, appointment = create_booked_referral(
        provider_id, patient_id, specialist_id, scheduled_start, scheduled_end,
        coordinator_user_id=coordinator_user_id, **referral_overrides,
    )
    confirm_appointment(appointment["id"])
    set_clock(complete_at or scheduled_start)
    complete_appointment(appointment["id"], specialist_id)
    return get_referral(referral["id"]), appointment


def create_pending_verification_referral(provider_id, patient_id, specialist_id,
                                         scheduled_start, scheduled_end,
                                         complete_at=None,
                                         coordinator_user_id="coord-1",
                                         note_summary="OK",
                                         **referral_overrides):
    """Completed + first consult note. Returns (referral, appointment, note)."""
    referral, appointment = create_completed_referral(
        provider_id, patient_id, specialist_id, scheduled_start, scheduled_end,
        complete_at=complete_at, coordinator_user_id=coordinator_user_id,
        **referral_overrides,
    )
    note = submit_consult_note(appointment["id"], specialist_id,
                               findings_summary=note_summary)
    return get_referral(referral["id"]), appointment, note


def verify_loop(referral, outcome="VERIFIED_CLOSED", verification_note="Loop verified",
                auditor_user_id="audit-1"):
    """Post a loop closure with the referral's current version. Returns LoopClosure."""
    return get_success_data(api_client.create_loop_closure(
        referral["id"],
        loop_closure_payload(referral["version"], outcome,
                             verification_note=verification_note),
        make_auditor_headers(auditor_user_id),
    ))


def create_closed_referral(provider_id, patient_id, specialist_id,
                           scheduled_start, scheduled_end, complete_at=None,
                           coordinator_user_id="coord-1", auditor_user_id="audit-1",
                           **referral_overrides):
    """Full lifecycle through CLOSED. Returns (referral, appointment, note, closure)."""
    referral, appointment, note = create_pending_verification_referral(
        provider_id, patient_id, specialist_id, scheduled_start, scheduled_end,
        complete_at=complete_at, coordinator_user_id=coordinator_user_id,
        **referral_overrides,
    )
    closure = verify_loop(referral, outcome="VERIFIED_CLOSED",
                          auditor_user_id=auditor_user_id)
    return get_referral(referral["id"]), appointment, note, closure


# --- Tier 4: accumulation helpers --------------------------------------------

def create_booked_referral_at(scenario, day_start, diagnosis_code,
                              coordinator_user_id="coord-1", urgency="ROUTINE"):
    """Create a referral in `scenario` and book it at [day_start, day_start+1h).

    `day_start` is an ISO timestamp like "2026-08-01T10:00:00Z"; the end is
    derived by the caller-facing convention of one-hour visits.
    Returns (referral, appointment).
    """
    from datetime import datetime, timedelta

    start = datetime.fromisoformat(day_start.replace("Z", "+00:00"))
    end = (start + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    return create_booked_referral(
        scenario["provider"]["id"], scenario["patient"]["id"],
        scenario["specialist"]["id"], day_start, end,
        coordinator_user_id=coordinator_user_id, diagnosis_code=diagnosis_code,
        urgency=urgency,
    )


def document_choice(referral_id, choice_type, note=""):
    return get_success_data(api_client.document_patient_choice(
        referral_id, document_patient_choice_payload(choice_type, note), COORD
    ))


def run_aging_sweep():
    return get_success_data(api_client.run_aging_sweep(COORD))


def list_referral_leakage_records(referral_id):
    data, _meta = validate_paginated(
        api_client.list_referral_leakage_records(referral_id, COORD)
    )
    return data


def list_provider_leakage_records(provider_id):
    data, _meta = validate_paginated(
        api_client.list_provider_leakage_records(provider_id, COORD)
    )
    return data


def list_referral_authorization_records(referral_id):
    data, _meta = validate_paginated(
        api_client.list_referral_authorization_records(referral_id, COORD)
    )
    return data


def list_snapshots():
    data, _meta = validate_paginated(api_client.list_snapshots(ADMIN))
    return data


def get_specialist(specialist_id):
    return get_success_data(api_client.get_specialist(specialist_id, COORD))


def get_patient(patient_id):
    return get_success_data(api_client.get_patient(patient_id, COORD))


def get_provider(provider_id):
    return get_success_data(api_client.get_referring_provider(provider_id, COORD))


def get_appointment(appointment_id):
    return get_success_data(api_client.get_appointment(appointment_id, COORD))
