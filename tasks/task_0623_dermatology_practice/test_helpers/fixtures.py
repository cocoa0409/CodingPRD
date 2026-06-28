"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) so setup failures surface as clear
"Setup failed" errors rather than confusing assertion failures.

Identity threading: the Provider role is entity-backed. Every fixture that creates a
Provider and then performs an ownership-gated Provider call (encounter start/clinical-close,
biopsy collect/lab/sign-out/cancel, booking complete) threads the actual provider id via
make_provider_headers(provider["id"]).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_provider_payload, create_room_payload, create_patient_payload,
    create_encounter_payload, create_biopsy_payload,
    create_procedure_booking_payload, create_prior_authorization_payload,
    create_step_therapy_trial_payload, create_cosmetic_membership_payload,
    create_cosmetic_treatment_payload, create_charge_payload,
    create_recall_reminder_payload,
)
from .test_users import TEST_USERS, make_provider_headers


# ─── Role-header shortcuts ────────────────────────────────────────────────
ADMIN = TEST_USERS["practice_admin_headers"]
FRONT = TEST_USERS["front_desk_headers"]
BILLING = TEST_USERS["billing_specialist_headers"]
PATHLAB = TEST_USERS["path_lab_headers"]


# ─── Clock control ────────────────────────────────────────────────────────
def set_clock(to_iso8601: str):
    """Set the server logical clock to an absolute UTC instant."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ─── Tier 1: Base entity builders ─────────────────────────────────────────
def create_provider(**overrides):
    """Create a provider. Returns the provider entity."""
    return get_success_data(
        api_client.create_provider(create_provider_payload(**overrides), ADMIN)
    )


def create_room(**overrides):
    """Create a room. Returns the room entity."""
    return get_success_data(
        api_client.create_room(create_room_payload(**overrides), ADMIN)
    )


def create_patient(**overrides):
    """Register a patient. Returns the patient entity."""
    return get_success_data(
        api_client.create_patient(create_patient_payload(**overrides), FRONT)
    )


def create_encounter(patient_id, provider_id, **overrides):
    """Schedule an encounter. Returns the encounter entity."""
    return get_success_data(
        api_client.create_encounter(
            create_encounter_payload(patient_id, provider_id, **overrides), FRONT
        )
    )


# ─── Tier 2: Provider + patient + encounter scenarios ─────────────────────
def setup_provider_patient_encounter(patient_overrides=None, encounter_overrides=None,
                                     provider_overrides=None):
    """Active provider + patient + a SCHEDULED encounter (BILLING_OPEN).

    Returns (provider, patient, encounter)."""
    provider = create_provider(**(provider_overrides or {}))
    patient = create_patient(**(patient_overrides or {}))
    encounter = create_encounter(patient["id"], provider["id"], **(encounter_overrides or {}))
    return provider, patient, encounter


def setup_encounter_in_progress(patient_overrides=None, encounter_overrides=None,
                                provider_overrides=None):
    """Drive a MEDICAL encounter to IN_PROGRESS (checked-in, started).

    Returns (provider, patient, encounter_in_progress)."""
    provider, patient, encounter = setup_provider_patient_encounter(
        patient_overrides, encounter_overrides, provider_overrides
    )
    prov_headers = make_provider_headers(provider["id"])
    get_success_data(api_client.check_in_encounter(encounter["id"], FRONT))
    enc = get_success_data(api_client.start_encounter(encounter["id"], prov_headers))
    return provider, patient, enc


def setup_encounter_clinically_closed(patient_overrides=None, encounter_overrides=None):
    """Drive a MEDICAL encounter (no biopsies) to CLINICALLY_CLOSED.

    Returns (provider, patient, encounter)."""
    provider, patient, enc = setup_encounter_in_progress(
        patient_overrides, encounter_overrides
    )
    prov_headers = make_provider_headers(provider["id"])
    enc = get_success_data(api_client.clinical_close_encounter(enc["id"], prov_headers))
    return provider, patient, enc


def setup_encounter_billing_finalized(patient_overrides=None, encounter_overrides=None):
    """Drive a MEDICAL encounter through CLINICALLY_CLOSED then BILLING_FINALIZED.

    Returns (provider, patient, encounter)."""
    provider, patient, enc = setup_encounter_clinically_closed(
        patient_overrides, encounter_overrides
    )
    enc = get_success_data(api_client.finalize_billing(enc["id"], BILLING))
    return provider, patient, enc


# ─── Tier 3: Biopsy lifecycle shortcuts ───────────────────────────────────
def collect_biopsy(encounter_id, provider_id, **overrides):
    """Collect a biopsy on an IN_PROGRESS encounter. Returns the biopsy entity."""
    prov_headers = make_provider_headers(provider_id)
    return get_success_data(
        api_client.create_biopsy(create_biopsy_payload(encounter_id, **overrides), prov_headers)
    )


def setup_biopsy_in_state(target_status, result=None,
                          patient_overrides=None, encounter_overrides=None):
    """Walk a biopsy COLLECTED -> AT_LAB -> RESULTED(result) -> SIGNED_OUT to target_status.

    target_status one of COLLECTED, AT_LAB, RESULTED, SIGNED_OUT.
    When target_status is RESULTED or SIGNED_OUT, `result` is required.
    Returns (provider, patient, encounter, biopsy)."""
    provider, patient, enc = setup_encounter_in_progress(
        patient_overrides, encounter_overrides
    )
    prov_headers = make_provider_headers(provider["id"])
    biopsy = get_success_data(
        api_client.create_biopsy(create_biopsy_payload(enc["id"]), prov_headers)
    )
    if target_status == "COLLECTED":
        return provider, patient, enc, biopsy
    get_success_data(api_client.send_biopsy_to_lab(biopsy["id"], prov_headers))
    if target_status == "AT_LAB":
        biopsy = get_success_data(api_client.get_biopsy(biopsy["id"], prov_headers))
        return provider, patient, enc, biopsy
    get_success_data(api_client.result_biopsy(biopsy["id"], {"result": result}, PATHLAB))
    if target_status == "RESULTED":
        biopsy = get_success_data(api_client.get_biopsy(biopsy["id"], prov_headers))
        return provider, patient, enc, biopsy
    biopsy = get_success_data(api_client.sign_out_biopsy(biopsy["id"], prov_headers))
    return provider, patient, enc, biopsy


# ─── Tier 4: Procedure booking / room ─────────────────────────────────────
def setup_room_with_booking(room_overrides=None, booking_overrides=None,
                            patient_overrides=None):
    """STANDARD room + provider + MEDICAL encounter + one BOOKED interval.

    Returns (provider, patient, encounter, room, booking, room_version_after).
    room_version_after is the room's version after the first booking (use it as the
    expected_room_version for a subsequent booking)."""
    provider = create_provider()
    patient = create_patient(**(patient_overrides or {}))
    encounter = create_encounter(patient["id"], provider["id"])
    room = create_room(**(room_overrides or {}))
    booking = get_success_data(api_client.create_procedure_booking(
        create_procedure_booking_payload(
            room["id"], provider["id"], encounter["id"], room["version"],
            **(booking_overrides or {})
        ), FRONT
    ))
    room_after = get_success_data(api_client.get_room(room["id"], ADMIN))
    return provider, patient, encounter, room, booking, room_after["version"]


# ─── Tier 5: Cosmetic membership / treatment ──────────────────────────────
def setup_active_membership(tier="SILVER", purchased_unit_cents=100000,
                            patient_overrides=None, patient=None):
    """Create + activate a cosmetic membership. Returns (patient, membership)."""
    if patient is None:
        patient = create_patient(**(patient_overrides or {}))
    membership = get_success_data(api_client.create_cosmetic_membership(
        create_cosmetic_membership_payload(
            patient["id"], tier=tier, purchased_unit_cents=purchased_unit_cents
        ), BILLING
    ))
    membership = get_success_data(
        api_client.activate_cosmetic_membership(membership["id"], BILLING)
    )
    return patient, membership


def setup_cosmetic_encounter_with_membership(tier="GOLD", purchased_unit_cents=50000,
                                             patient_overrides=None):
    """COSMETIC encounter + an ACTIVE membership for the same patient.

    Returns (provider, patient, encounter, membership)."""
    provider = create_provider()
    patient = create_patient(**(patient_overrides or {}))
    encounter = create_encounter(
        patient["id"], provider["id"], visit_type="COSMETIC",
        scheduled_at="2026-01-17T09:00:00Z"
    )
    _, membership = setup_active_membership(
        tier=tier, purchased_unit_cents=purchased_unit_cents, patient=patient
    )
    return provider, patient, encounter, membership


def redeem_treatment(encounter_id, membership_id, expected_membership_version, **overrides):
    """Redeem a cosmetic treatment. Returns the treatment entity."""
    return get_success_data(api_client.create_cosmetic_treatment(
        create_cosmetic_treatment_payload(
            encounter_id, membership_id, expected_membership_version, **overrides
        ), BILLING
    ))


# ─── Tier 6: Prior authorization / step therapy ───────────────────────────
def setup_prior_authorization(patient=None, required_step_count=0, list_price_cents=100000,
                              patient_overrides=None):
    """Create a DRAFT PriorAuthorization. Returns (patient, pa)."""
    if patient is None:
        patient = create_patient(**(patient_overrides or {}))
    pa = get_success_data(api_client.create_prior_authorization(
        create_prior_authorization_payload(
            patient["id"], required_step_count=required_step_count,
            list_price_cents=list_price_cents
        ), BILLING
    ))
    return patient, pa


def setup_approved_pa_round(patient, list_price_cents, target_round):
    """Drive a PriorAuthorization to APPROVED on a given submission_round.

    target_round == 1: one FAILED trial -> submit -> approve (submission_round 1).
    target_round == 2: one FAILED trial -> submit -> deny -> second FAILED trial ->
                       submit -> approve (submission_round 2).
    Returns the APPROVED pa entity."""
    pa = get_success_data(api_client.create_prior_authorization(
        create_prior_authorization_payload(
            patient["id"], required_step_count=1, list_price_cents=list_price_cents
        ), BILLING
    ))
    get_success_data(api_client.create_step_therapy_trial(
        pa["id"], create_step_therapy_trial_payload(drug_name="old-drug-1"), BILLING
    ))
    get_success_data(api_client.submit_prior_authorization(pa["id"], BILLING))
    if target_round >= 2:
        get_success_data(api_client.adjudicate_prior_authorization(
            pa["id"], {"decision": "DENY"}, BILLING
        ))
        get_success_data(api_client.create_step_therapy_trial(
            pa["id"], create_step_therapy_trial_payload(drug_name="old-drug-2"), BILLING
        ))
        get_success_data(api_client.submit_prior_authorization(pa["id"], BILLING))
    pa = get_success_data(api_client.adjudicate_prior_authorization(
        pa["id"], {"decision": "APPROVE"}, BILLING
    ))
    return pa


# ─── Tier 7: Charges ──────────────────────────────────────────────────────
def post_charge(patient_id, encounter_id, **overrides):
    """Post a charge. Returns the charge entity."""
    return get_success_data(api_client.create_charge(
        create_charge_payload(patient_id, encounter_id, **overrides), BILLING
    ))
