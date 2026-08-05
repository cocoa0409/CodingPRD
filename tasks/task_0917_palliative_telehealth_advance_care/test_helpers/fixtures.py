"""Composite setup helpers.

The harness restarts the API server before every individual test, so each test
starts against an empty database. Every helper below therefore builds its
preconditions from scratch using only the endpoints the PRD declares.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import BASE_CLOCK, IDT_DISCIPLINES, USER_IDS
from . import factories as f
from .test_users import TEST_USERS, make_caregiver_headers

ADMIN = TEST_USERS["admin_headers"]
INTAKE = TEST_USERS["intake_headers"]
PHYSICIAN = TEST_USERS["physician_headers"]
PHYSICIAN_2 = TEST_USERS["physician_2_headers"]
NURSE = TEST_USERS["nurse_headers"]
SOCIAL_WORKER = TEST_USERS["social_worker_headers"]
CHAPLAIN = TEST_USERS["chaplain_headers"]
HOSPICE_DIRECTOR = TEST_USERS["hospice_director_headers"]
ONCALL = TEST_USERS["oncall_headers"]
BILLING = TEST_USERS["billing_headers"]

DISCIPLINE_HEADERS = {
    "PHYSICIAN": PHYSICIAN,
    "NURSE": NURSE,
    "SOCIAL_WORKER": SOCIAL_WORKER,
    "CHAPLAIN": CHAPLAIN,
}


def _data(response, what: str) -> dict:
    """Lenient extraction with a clear message when setup goes wrong."""
    if response.status_code >= 300:
        raise AssertionError(
            f"Setup failed while {what}: HTTP {response.status_code} {response.text}"
        )
    return get_success_data(response)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
def set_clock(instant: str) -> dict:
    """Move the server's logical clock and return the response payload."""
    return _data(api_client.set_clock(instant, ADMIN), f"setting the clock to {instant}")


# ---------------------------------------------------------------------------
# Tier 1 — patients and referrals
# ---------------------------------------------------------------------------
def register_patient(clock=BASE_CLOCK, **overrides) -> dict:
    """Register one patient; the row opens in program_status REFERRED."""
    if clock is not None:
        set_clock(clock)
    return _data(
        api_client.create_patient(f.patient_payload(**overrides), INTAKE),
        "registering a patient",
    )


def file_referral(patient_id, **overrides) -> dict:
    return _data(
        api_client.create_referral(f.referral_payload(patient_id, **overrides), INTAKE),
        "filing a referral",
    )


def enroll_patient(clock=BASE_CLOCK, referral_overrides=None, **overrides):
    """Register a patient and accept a referral, leaving them program_status ACTIVE.

    Returns (patient, referral) as the API last rendered them.
    """
    patient = register_patient(clock=clock, **overrides)
    referral = file_referral(patient["id"], **(referral_overrides or {}))
    referral = _data(
        api_client.decide_referral(
            referral["id"], f.referral_decision_payload("ACCEPT"), INTAKE
        ),
        "accepting a referral",
    )
    return read_patient(patient["id"]), referral


def read_patient(patient_id) -> dict:
    return _data(api_client.get_patient(patient_id, ADMIN), "reading a patient")


def patient_version(patient_id) -> int:
    return read_patient(patient_id)["version"]


# ---------------------------------------------------------------------------
# Tier 1 — surrogates and capacity
# ---------------------------------------------------------------------------
def designate_surrogate(patient_id, activate=False, **overrides) -> dict:
    designation = _data(
        api_client.create_surrogate(f.surrogate_payload(patient_id, **overrides), SOCIAL_WORKER),
        "designating a surrogate",
    )
    if activate:
        designation = _data(
            api_client.set_surrogate_status(
                designation["id"], {"target_status": "ACTIVE"}, SOCIAL_WORKER
            ),
            "activating a surrogate designation",
        )
    return designation


def determine_capacity(patient_id, capacity_status, note=None) -> dict:
    payload = f.capacity_determination_payload(capacity_status)
    if note is not None:
        payload["determination_note"] = note
    return _data(
        api_client.create_capacity_determination(patient_id, payload, PHYSICIAN),
        f"determining capacity {capacity_status}",
    )


def caregiver_headers_for(designation: dict) -> dict:
    """Headers for the Caregiver role acting as this surrogate designation."""
    return make_caregiver_headers(designation["id"])


# ---------------------------------------------------------------------------
# Tier 2 — advance care documents
# ---------------------------------------------------------------------------
def draft_document(patient_id, **overrides) -> dict:
    return _data(
        api_client.create_document(f.document_payload(patient_id, **overrides), SOCIAL_WORKER),
        "drafting an advance care document",
    )


def sign_document(document_id, signature_type="WITNESS", signer_user_id=None, headers=None) -> dict:
    return _data(
        api_client.add_document_signature(
            document_id,
            f.signature_payload(signature_type, signer_user_id),
            headers or SOCIAL_WORKER,
        ),
        f"appending a {signature_type} signature",
    )


def witnessed_document(patient_id, witnesses=2, **overrides) -> dict:
    """A document carrying `witnesses` independent WITNESS signatures."""
    document = draft_document(patient_id, **overrides)
    pool = [USER_IDS["WITNESS_1"], USER_IDS["WITNESS_2"]]
    for index in range(witnesses):
        document = sign_document(document["id"], "WITNESS", pool[index % len(pool)])
    return document


def executed_document(patient_id, **overrides) -> dict:
    """Draft, witness twice and execute, returning the executed document."""
    document = witnessed_document(patient_id, **overrides)
    return _data(
        api_client.execute_document(
            document["id"],
            {"expected_patient_version": patient_version(patient_id)},
            PHYSICIAN,
        ),
        "executing an advance care document",
    )


# ---------------------------------------------------------------------------
# Tier 2 — code-status orders
# ---------------------------------------------------------------------------
def draft_code_status_order(patient_id, requested_code_status="DNR", **overrides) -> dict:
    return _data(
        api_client.create_code_status_order(
            f.code_status_order_payload(patient_id, requested_code_status, **overrides),
            PHYSICIAN,
        ),
        "drafting a code-status order",
    )


def effective_code_status_order(patient_id, requested_code_status="DNR", **overrides) -> dict:
    """Draft an order and carry it through both attestations to EFFECTIVE."""
    order = draft_code_status_order(patient_id, requested_code_status, **overrides)
    _data(
        api_client.attest_code_status_order(
            order["id"], f.code_status_attestation_payload("CLINICIAN"), PHYSICIAN
        ),
        "recording the clinician attestation",
    )
    return _data(
        api_client.attest_code_status_order(
            order["id"],
            f.code_status_attestation_payload("PATIENT_OR_SURROGATE"),
            SOCIAL_WORKER,
        ),
        "recording the patient-or-surrogate attestation",
    )


# ---------------------------------------------------------------------------
# Tier 2 — care plans and symptom assessments
# ---------------------------------------------------------------------------
def draft_care_plan(patient_id, **overrides) -> dict:
    return _data(
        api_client.create_care_plan(f.care_plan_payload(patient_id, **overrides), NURSE),
        "creating a care plan",
    )


def active_care_plan(patient_id, **overrides) -> dict:
    plan = draft_care_plan(patient_id, **overrides)
    return _data(
        api_client.activate_care_plan(plan["id"], {}, NURSE),
        "activating a care plan",
    )


def read_care_plan(plan_id) -> dict:
    return _data(api_client.get_care_plan(plan_id, NURSE), "reading a care plan")


def file_symptom_assessment(patient_id, care_plan_id, headers=None, **overrides) -> dict:
    return _data(
        api_client.create_symptom_assessment(
            f.symptom_assessment_payload(patient_id, care_plan_id, **overrides),
            headers or NURSE,
        ),
        "filing a symptom assessment",
    )


def patient_with_open_symptom(clock=BASE_CLOCK, assessment_overrides=None, **overrides):
    """Enrolled patient + ACTIVE care plan + one OPEN symptom assessment.

    Returns (patient, care_plan, assessment).
    """
    patient, _ = enroll_patient(clock=clock, **overrides)
    plan = active_care_plan(patient["id"])
    assessment = file_symptom_assessment(
        patient["id"], plan["id"], **(assessment_overrides or {})
    )
    return read_patient(patient["id"]), plan, assessment


# ---------------------------------------------------------------------------
# Tier 2 — after-hours escalations
# ---------------------------------------------------------------------------
def open_escalation(patient_id, assessment_id, **overrides) -> dict:
    return _data(
        api_client.create_escalation(
            f.escalation_payload(patient_id, assessment_id, **overrides), ONCALL
        ),
        "opening an escalation",
    )


def dispositioned_escalation(patient_id, assessment_id, disposition="URGENT_TELEHEALTH_VISIT") -> dict:
    escalation = open_escalation(patient_id, assessment_id)
    _data(
        api_client.respond_escalation(
            escalation["id"], f.escalation_response_payload("ACKNOWLEDGE"), ONCALL
        ),
        "acknowledging an escalation",
    )
    return _data(
        api_client.respond_escalation(
            escalation["id"],
            f.escalation_response_payload("DISPOSITION", disposition=disposition),
            ONCALL,
        ),
        "dispositioning an escalation",
    )


# ---------------------------------------------------------------------------
# Tier 3 — conferences
# ---------------------------------------------------------------------------
def book_conference(patient_id, **overrides) -> dict:
    return _data(
        api_client.create_conference(f.conference_payload(patient_id, **overrides), SOCIAL_WORKER),
        "booking a conference",
    )


def hold_conference(conference_id, documented_minutes=46, **overrides) -> dict:
    return _data(
        api_client.hold_conference(
            conference_id,
            f.conference_hold_payload(documented_minutes, **overrides),
            SOCIAL_WORKER,
        ),
        "holding a conference",
    )


def attest_conference(conference_id, discipline, note_text=None) -> dict:
    payload = f.conference_attestation_payload(discipline)
    if note_text is not None:
        payload["note_text"] = note_text
    return _data(
        api_client.attest_conference(conference_id, payload, DISCIPLINE_HEADERS[discipline]),
        f"attesting the {discipline} note",
    )


def attested_idt_conference(
    patient_id,
    scheduled_start="2026-06-02T09:00:00Z",
    scheduled_end="2026-06-02T10:00:00Z",
    held_at="2026-06-02T09:00:00Z",
    documented_minutes=46,
) -> dict:
    """Book, hold with full quorum and attest all four disciplines.

    Leaves the logical clock at `held_at`, which is what the cadence rule reads.
    """
    conference = book_conference(
        patient_id,
        conference_type="IDT",
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
    )
    set_clock(held_at)
    hold_conference(
        conference["id"],
        documented_minutes=documented_minutes,
        disciplines_present=list(IDT_DISCIPLINES),
    )
    result = None
    for discipline in IDT_DISCIPLINES:
        result = attest_conference(conference["id"], discipline)
    return result


def held_family_conference(patient_id, documented_minutes=46, disciplines=None, **overrides):
    """Book a FAMILY conference and hold it, returning the held conference."""
    conference = book_conference(
        patient_id,
        conference_type="FAMILY",
        **{k: v for k, v in overrides.items() if k in
           ("scheduled_start", "scheduled_end", "modality")},
    )
    hold_kwargs = {}
    if disciplines is not None:
        hold_kwargs["disciplines_present"] = disciplines
    if "decision_maker_id" in overrides:
        hold_kwargs["decision_maker_id"] = overrides["decision_maker_id"]
    return hold_conference(conference["id"], documented_minutes, **hold_kwargs)


# ---------------------------------------------------------------------------
# Tier 3 — medication orders
# ---------------------------------------------------------------------------
def write_medication_order(patient_id, **overrides) -> dict:
    return _data(
        api_client.create_medication_order(
            f.medication_order_payload(patient_id, **overrides), PHYSICIAN
        ),
        "writing a medication order",
    )


def verify_medication_order(order_id, note=None) -> dict:
    """Second-clinician VERIFICATION. The verifier is never the prescriber."""
    payload = f.medication_attestation_payload("VERIFICATION")
    if note is not None:
        payload["attestation_note"] = note
    return _data(
        api_client.attest_medication_order(order_id, payload, NURSE),
        "verifying a medication order",
    )


def mme_review_medication_order(order_id, note="risk-benefit reviewed") -> dict:
    """MME_REVIEW by a physician who is not the prescriber."""
    return _data(
        api_client.attest_medication_order(
            order_id,
            f.medication_attestation_payload("MME_REVIEW", attestation_note=note),
            PHYSICIAN_2,
        ),
        "recording an MME review",
    )


def active_medication_order(patient_id, **overrides) -> dict:
    """Write an order and verify it into ACTIVE."""
    order = write_medication_order(patient_id, **overrides)
    return verify_medication_order(order["id"])


# ---------------------------------------------------------------------------
# Tier 3 — equipment
# ---------------------------------------------------------------------------
def stock_inventory(**overrides) -> dict:
    return _data(
        api_client.create_dme_inventory(f.dme_inventory_payload(**overrides), ADMIN),
        "stocking an inventory line",
    )


def read_inventory(inventory_id) -> dict:
    return _data(
        api_client.get_dme_inventory(inventory_id, ADMIN), "reading an inventory line"
    )


def request_equipment(patient_id, inventory_item_id, **overrides) -> dict:
    return _data(
        api_client.create_dme_order(
            f.dme_order_payload(patient_id, inventory_item_id, **overrides), NURSE
        ),
        "requesting equipment",
    )


def authorize_equipment(order_id, reference="PA-2026-0001") -> dict:
    return _data(
        api_client.authorize_dme_order(order_id, {"prior_auth_reference": reference}, ADMIN),
        "authorising an equipment order",
    )


def schedule_equipment(order_id) -> dict:
    return _data(
        api_client.fulfill_dme_order(order_id, {"event": "SCHEDULED"}, NURSE),
        "scheduling an equipment delivery",
    )


def deliver_equipment(order_id) -> dict:
    return _data(
        api_client.fulfill_dme_order(order_id, {"event": "DELIVERED"}, NURSE),
        "recording an equipment delivery",
    )


def delivered_equipment_order(patient_id, inventory_item_id, **overrides) -> dict:
    order = request_equipment(patient_id, inventory_item_id, **overrides)
    schedule_equipment(order["id"])
    return deliver_equipment(order["id"])


# ---------------------------------------------------------------------------
# Tier 4 — hospice election
# ---------------------------------------------------------------------------
def open_hospice_election(patient_id, **overrides) -> dict:
    return _data(
        api_client.create_hospice_election(
            f.hospice_election_payload(patient_id, **overrides), PHYSICIAN
        ),
        "opening a hospice election",
    )


def certified_hospice_election(patient_id, diagnosis="C34.90", **overrides) -> dict:
    """Open an election and certify it twice, from two different physicians."""
    election = open_hospice_election(patient_id, **overrides)
    _data(
        api_client.certify_hospice_election(
            election["id"], f.hospice_certification_payload(diagnosis), PHYSICIAN
        ),
        "recording the attending certification",
    )
    return _data(
        api_client.certify_hospice_election(
            election["id"], f.hospice_certification_payload(diagnosis), HOSPICE_DIRECTOR
        ),
        "recording the hospice director certification",
    )


def read_election(election_id) -> dict:
    return _data(
        api_client.get_hospice_election(election_id, HOSPICE_DIRECTOR),
        "reading a hospice election",
    )


def open_benefit_period(election_id, period_start, expected_version=None, **overrides) -> dict:
    version = (
        expected_version
        if expected_version is not None
        else read_election(election_id)["version"]
    )
    return _data(
        api_client.open_hospice_period(
            election_id,
            f.hospice_period_payload(version, period_start, **overrides),
            HOSPICE_DIRECTOR,
        ),
        f"opening a benefit period starting {period_start}",
    )


def elected_hospice_patient(
    clock=BASE_CLOCK,
    conference_held_at="2026-06-02T09:00:00Z",
    period_start="2026-06-02T00:00:00Z",
    election_overrides=None,
    **overrides,
):
    """Enrolled patient -> attested IDT conference -> certified election -> period 1.

    Returns (patient, election). The logical clock is left at
    `conference_held_at`, which keeps interdisciplinary cadence satisfied.
    """
    patient, _ = enroll_patient(clock=clock, **overrides)
    attested_idt_conference(patient["id"], held_at=conference_held_at)
    election = certified_hospice_election(patient["id"], **(election_overrides or {}))
    election = open_benefit_period(election["id"], period_start, election["version"])
    return read_patient(patient["id"]), election


# ---------------------------------------------------------------------------
# Tier 4 — claims
# ---------------------------------------------------------------------------
def create_claim(patient_id, **overrides) -> dict:
    return _data(
        api_client.create_claim(f.claim_payload(patient_id, **overrides), BILLING),
        "creating a claim",
    )


def attest_claim(claim_id, statement=None) -> dict:
    payload = f.claim_attest_payload()
    if statement is not None:
        payload["attestation_statement"] = statement
    return _data(api_client.attest_claim(claim_id, payload, BILLING), "attesting a claim")


def submit_claim(claim_id, note=None) -> dict:
    payload = {} if note is None else {"submission_note": note}
    return _data(api_client.submit_claim(claim_id, payload, BILLING), "submitting a claim")


def adjudicate_claim(claim_id, outcome="PAID", denial_reason=None) -> dict:
    payload = f.adjudication_payload(outcome)
    if denial_reason is not None:
        payload["denial_reason"] = denial_reason
    return _data(
        api_client.adjudicate_claim(claim_id, payload, ADMIN), "adjudicating a claim"
    )


def paid_claim(patient_id, **overrides) -> dict:
    """Create, attest, submit and pay one claim."""
    claim = create_claim(patient_id, **overrides)
    attest_claim(claim["id"])
    submit_claim(claim["id"])
    return adjudicate_claim(claim["id"], "PAID")


# ---------------------------------------------------------------------------
# Tier 5 — death and the records freeze
# ---------------------------------------------------------------------------
def record_death(patient_id, pronouncing_user_id=None) -> dict:
    payload = f.death_event_payload()
    if pronouncing_user_id is not None:
        payload["pronouncing_clinician_user_id"] = pronouncing_user_id
    return _data(
        api_client.create_death_event(patient_id, payload, PHYSICIAN),
        "recording a death event",
    )


def frozen_patient(clock=BASE_CLOCK, **overrides):
    """Enrolled patient with an ACTIVE care plan, then pronounced dead.

    Returns (patient_after_death, care_plan).
    """
    patient, _ = enroll_patient(clock=clock, **overrides)
    plan = active_care_plan(patient["id"])
    deceased = record_death(patient["id"])
    return deceased, plan
