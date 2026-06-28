"""Non-linear state machines: prior-authorization cyclic resubmission loop and the
encounter's two independent clinical/billing dimensions."""
import pytest
from test_helpers import (
    validate_success, get_success_data,
    create_patient, setup_provider_patient_encounter, setup_encounter_clinically_closed,
    api_client,
    TEST_USERS,
)
from test_helpers.test_users import make_provider_headers

BILLING = TEST_USERS["billing_specialist_headers"]
FRONT = TEST_USERS["front_desk_headers"]


def test_prior_auth_cyclic_resubmission_after_denial(api):
    """PRD §3.9: "After a denial the practice adds another step-therapy trial and resubmits:
    the `DENIED → SUBMITTED` transition requires the current status to be `DENIED` (otherwise
    `ERR_PA_BAD_STATE`) and again requires step therapy to be met against the freshly
    augmented trials (otherwise `ERR_STEP_THERAPY_NOT_MET`); this resubmission likewise
    increments the `version` and increments `submission_round` by one."

    Design: Difficulty/non_linear_state_machine/prior_auth_cyclic_resubmission_after_denial
    """
    patient = create_patient(full_name="Cyc Pat", date_of_birth="1970-06-06")
    pa = validate_success(api.create_prior_authorization({
        "patient_id": patient["id"], "drug_name": "biologic-Y",
        "required_step_count": 1, "list_price_cents": 50000,
    }, BILLING), 201)
    validate_success(api.create_step_therapy_trial(
        pa["id"], {"drug_name": "step-1", "outcome": "FAILED"}, BILLING), 201)
    validate_success(api.submit_prior_authorization(pa["id"], BILLING), 200)
    validate_success(api.adjudicate_prior_authorization(
        pa["id"], {"decision": "DENY"}, BILLING), 200)
    validate_success(api.create_step_therapy_trial(
        pa["id"], {"drug_name": "step-2", "outcome": "FAILED"}, BILLING), 201)

    resubmitted = validate_success(api.submit_prior_authorization(pa["id"], BILLING), 200)
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["submission_round"] == 2


def test_prior_auth_first_submission_round_is_one(api):
    """PRD §3.9: "A `BillingSpecialist` submits a prior authorization, moving
    `DRAFT → SUBMITTED`. Submission requires the current status to be `DRAFT` (otherwise
    `ERR_PA_BAD_STATE`) and requires step therapy to be met, that is, `satisfied_step_count`
    at least `required_step_count` (otherwise `ERR_STEP_THERAPY_NOT_MET`). Submission
    increments the prior authorization's `version` and increments its `submission_round` by
    one."

    Design: Difficulty/non_linear_state_machine/prior_auth_cyclic_resubmission_after_denial
    """
    patient = create_patient(full_name="Round Pat", date_of_birth="1971-06-06")
    pa = validate_success(api.create_prior_authorization({
        "patient_id": patient["id"], "drug_name": "biologic-Y2",
        "required_step_count": 0, "list_price_cents": 50000,
    }, BILLING), 201)
    assert pa["submission_round"] == 0
    submitted = validate_success(api.submit_prior_authorization(pa["id"], BILLING), 200)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["submission_round"] == 1


def test_encounter_parallel_clinical_and_billing_dimensions(api):
    """PRD §3.3: "A `BillingSpecialist` finalizes billing, moving
    `BILLING_OPEN → BILLING_FINALIZED`; this requires the encounter's `billing_status` to
    currently be `BILLING_OPEN` (otherwise `ERR_ENCOUNTER_BAD_BILLING_STATE`) and, as a
    cross-dimension guard, requires the `clinical_status` to already be `CLINICALLY_CLOSED`
    (otherwise `ERR_ENCOUNTER_NOT_CLINICALLY_CLOSED`)."

    Design: Difficulty/non_linear_state_machine/encounter_parallel_clinical_and_billing_dimensions
    """
    provider, patient, enc = setup_encounter_clinically_closed()
    assert enc["clinical_status"] == "CLINICALLY_CLOSED"
    assert enc["billing_status"] == "BILLING_OPEN"

    finalized = validate_success(api.finalize_billing(enc["id"], BILLING), 200)
    assert finalized["clinical_status"] == "CLINICALLY_CLOSED"
    assert finalized["billing_status"] == "BILLING_FINALIZED"


def test_encounter_clinical_close_leaves_billing_open(api):
    """PRD §3.3: "The **billing dimension** is entirely independent and advances
    `BILLING_OPEN → BILLING_FINALIZED`, with `BILLING_VOID` as an alternative terminal
    state."
    PRD §3.3: "On creation the encounter's `clinical_status` is `SCHEDULED`, its
    `billing_status` is `BILLING_OPEN`, and its `open_biopsy_count` is 0."

    Design: Difficulty/non_linear_state_machine/encounter_parallel_clinical_and_billing_dimensions
    """
    provider, patient, enc = setup_provider_patient_encounter()
    assert enc["clinical_status"] == "SCHEDULED"
    assert enc["billing_status"] == "BILLING_OPEN"

    prov_headers = make_provider_headers(provider["id"])
    validate_success(api.check_in_encounter(enc["id"], FRONT), 200)
    validate_success(api.start_encounter(enc["id"], prov_headers), 200)
    closed = validate_success(api.clinical_close_encounter(enc["id"], prov_headers), 200)
    # Driving clinical to closed must not advance the billing dimension.
    assert closed["clinical_status"] == "CLINICALLY_CLOSED"
    assert closed["billing_status"] == "BILLING_OPEN"
