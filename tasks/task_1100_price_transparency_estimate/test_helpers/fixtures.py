"""Composite setup helpers.

Each helper drives the real API through PRD-declared endpoints and uses the
lenient get_success_data() validator so a broken precondition surfaces as a
clear "Setup step failed" error. The test harness restarts the server (empty
DB) before every test, so every helper builds its world from scratch.

Version threading: create-estimate is OCC-guarded on Patient.version and
rate-ingest is OCC-guarded on PayerContract.version. Helpers fetch the current
version just before writing so callers never have to track it by hand.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULT_PLAN, GROSS_CHARGE_CENTS, FLAT_RATE_CENTS, TEST_CLOCK_UTC,
)
from .factories import (
    create_procedure_payload, create_payer_contract_payload,
    create_negotiated_rate_payload, create_benefit_plan_payload,
    create_patient_payload, create_provider_payload, create_room_payload,
    create_estimate_payload, create_line_payload,
    create_prior_authorization_payload, approve_prior_authorization_payload,
    create_appointment_payload, create_dispute_payload,
)
from .test_users import (
    TEST_USERS, make_patient_headers,
)

PROVIDER = TEST_USERS["provider_staff_headers"]
PAYER = TEST_USERS["payer_analyst_headers"]
ADMIN = TEST_USERS["admin_headers"]


# --------------------------------------------------------------------------
# Low-level single-step helpers
# --------------------------------------------------------------------------
def set_clock(api=api_client, iso=TEST_CLOCK_UTC):
    return get_success_data(api.set_clock(iso, ADMIN))


def new_benefit_plan(api=api_client, **over):
    payload = create_benefit_plan_payload(**over)
    return get_success_data(api.create_benefit_plan(payload, PAYER))


def new_patient(api, plan_id, **over):
    payload = create_patient_payload(plan_id, **over)
    return get_success_data(api.create_patient(payload, PROVIDER))


def patient_version(api, patient_id):
    return get_success_data(api.get_patient(patient_id, PROVIDER))["version"]


def adjust_accumulators(api, patient_id, deductible_delta_cents, oop_delta_cents,
                        source="EOB"):
    payload = {
        "deductible_delta_cents": deductible_delta_cents,
        "oop_delta_cents": oop_delta_cents,
        "source": source,
    }
    return get_success_data(
        api.create_accumulation_adjustment(patient_id, payload, PAYER))


def new_contract(api, **over):
    """Create a DRAFT payer contract."""
    payload = create_payer_contract_payload(**over)
    return get_success_data(api.create_payer_contract(payload, PAYER))


def activate_contract(api, contract_id):
    return get_success_data(api.activate_payer_contract(contract_id, PAYER))


def new_active_contract(api, **over):
    """Create and activate a payer contract; returns the ACTIVE contract."""
    contract = new_contract(api, **over)
    return activate_contract(api, contract["id"])


def new_procedure(api, **over):
    payload = create_procedure_payload(**over)
    return get_success_data(api.create_procedure(payload, PROVIDER))


def ingest_flat_rate(api, contract_id, procedure_id, flat_amount_cents=FLAT_RATE_CENTS,
                     expected_contract_version=None):
    if expected_contract_version is None:
        expected_contract_version = get_success_data(
            api.get_payer_contract(contract_id, PAYER))["version"]
    payload = create_negotiated_rate_payload(
        contract_id, procedure_id, expected_contract_version,
        rate_type="FLAT", flat_amount_cents=flat_amount_cents)
    return get_success_data(api.create_negotiated_rate(payload, PAYER))


def ingest_percent_rate(api, contract_id, procedure_id, percent_of_charge,
                        expected_contract_version=None):
    if expected_contract_version is None:
        expected_contract_version = get_success_data(
            api.get_payer_contract(contract_id, PAYER))["version"]
    payload = create_negotiated_rate_payload(
        contract_id, procedure_id, expected_contract_version,
        rate_type="PERCENT", percent_of_charge=percent_of_charge)
    return get_success_data(api.create_negotiated_rate(payload, PAYER))


def new_estimate(api, patient_id, estimate_type="GFE_INSURED", contract_id=None,
                 expected_patient_version=None):
    if expected_patient_version is None:
        expected_patient_version = patient_version(api, patient_id)
    payload = create_estimate_payload(
        patient_id, expected_patient_version,
        estimate_type=estimate_type, contract_id=contract_id)
    return get_success_data(api.create_estimate(payload, PROVIDER))


def add_line(api, estimate_id, procedure_id):
    return get_success_data(
        api.add_estimate_line(estimate_id, create_line_payload(procedure_id), PROVIDER))


def issue(api, estimate_id):
    return get_success_data(api.issue_estimate(estimate_id, PROVIDER))


def accept(api, estimate_id, patient_id):
    return get_success_data(
        api.accept_estimate(estimate_id, make_patient_headers(patient_id)))


def new_provider(api, **over):
    return get_success_data(api.create_provider(create_provider_payload(**over), PROVIDER))


def new_room(api, **over):
    return get_success_data(api.create_room(create_room_payload(**over), PROVIDER))


def request_prior_auth(api, estimate_id, procedure_code="70450", requested_units=1):
    payload = create_prior_authorization_payload(
        estimate_id, procedure_code=procedure_code, requested_units=requested_units)
    return get_success_data(api.create_prior_authorization(payload, PROVIDER))


def approve_prior_auth(api, prior_auth_id, auth_number="AUTH-1", approved_units=1,
                       expiration_date="2026-12-31T00:00:00Z"):
    payload = approve_prior_authorization_payload(
        auth_number=auth_number, approved_units=approved_units,
        expiration_date=expiration_date)
    return get_success_data(api.approve_prior_authorization(prior_auth_id, payload, PAYER))


def deny_prior_auth(api, prior_auth_id, denial_reason="Not medically necessary"):
    return get_success_data(
        api.deny_prior_authorization(prior_auth_id, {"denial_reason": denial_reason}, PAYER))


def schedule_appointment(api, patient_id, estimate_id, provider_id, room_id,
                         scheduled_start, scheduled_end, prior_auth_id=None):
    payload = create_appointment_payload(
        patient_id, estimate_id, provider_id, room_id,
        scheduled_start, scheduled_end, prior_auth_id=prior_auth_id)
    return get_success_data(api.create_appointment(payload, PROVIDER))


def complete_appointment(api, appointment_id):
    return get_success_data(api.complete_appointment(appointment_id, PROVIDER))


def file_dispute(api, estimate_id, patient_id, reason="Estimate too high",
                 disputed_amount_cents=5000):
    payload = create_dispute_payload(
        estimate_id, reason=reason, disputed_amount_cents=disputed_amount_cents)
    return get_success_data(
        api.create_dispute(payload, make_patient_headers(patient_id)))


def assign_dispute(api, dispute_id):
    return get_success_data(api.assign_dispute(dispute_id, PROVIDER))


# --------------------------------------------------------------------------
# Scenario builders
# --------------------------------------------------------------------------
def setup_insured_issued_single_line(api, plan_over=None, gross_charge_cents=GROSS_CHARGE_CENTS,
                                     flat_amount_cents=FLAT_RATE_CENTS, set_clock_first=False):
    """Fresh patient + ACTIVE contract + FLAT-rate procedure + single-line
    GFE_INSURED estimate, issued (status ISSUED). Returns a bundle dict.

    With the canonical plan and FLAT 200000 rate against a fresh patient this
    prices allowed_amount_cents=200000, patient_responsibility_cents=122500.
    """
    if set_clock_first:
        set_clock(api)
    plan = new_benefit_plan(api, **(plan_over or {}))
    patient = new_patient(api, plan["id"])
    contract = new_active_contract(api)
    procedure = new_procedure(api, gross_charge_cents=gross_charge_cents)
    rate = ingest_flat_rate(api, contract["id"], procedure["id"], flat_amount_cents)
    estimate = new_estimate(api, patient["id"], estimate_type="GFE_INSURED",
                            contract_id=contract["id"])
    line = add_line(api, estimate["id"], procedure["id"])
    issued = issue(api, estimate["id"])
    return {
        "plan": plan, "patient": patient, "contract": contract,
        "procedure": procedure, "rate": rate, "estimate": issued, "line": line,
    }


def setup_insured_accepted_single_line(api, requires_prior_auth=False, **kw):
    """Same as issued, but patient-accepted (status ACCEPTED), ready to schedule."""
    b = setup_insured_issued_single_line(api, set_clock_first=True, **kw)
    accepted = accept(api, b["estimate"]["id"], b["patient"]["id"])
    b["estimate"] = accepted
    return b


def setup_settled_estimate(api):
    """Full lifecycle to SETTLED: issue -> accept -> schedule -> complete.

    With the canonical plan, fresh patient and FLAT 200000 rate the estimate
    settles at patient_responsibility_cents=122500; the patient's accumulators
    become deductible_met_cents=100000, oop_met_cents=122500. Returns a bundle
    including the appointment and the patient snapshot after settlement.
    """
    set_clock(api)
    plan = new_benefit_plan(api)
    patient = new_patient(api, plan["id"])
    contract = new_active_contract(api)
    procedure = new_procedure(api)
    ingest_flat_rate(api, contract["id"], procedure["id"], FLAT_RATE_CENTS)
    estimate = new_estimate(api, patient["id"], estimate_type="GFE_INSURED",
                            contract_id=contract["id"])
    add_line(api, estimate["id"], procedure["id"])
    issue(api, estimate["id"])
    accept(api, estimate["id"], patient["id"])
    provider = new_provider(api)
    room = new_room(api)
    appt = schedule_appointment(
        api, patient["id"], estimate["id"], provider["id"], room["id"],
        "2026-06-02T10:00:00Z", "2026-06-02T11:00:00Z")
    completed = complete_appointment(api, appt["id"])
    patient_after = get_success_data(api.get_patient(patient["id"], PROVIDER))
    settled = get_success_data(api.get_estimate(estimate["id"], PROVIDER))
    return {
        "plan": plan, "patient": patient_after, "contract": contract,
        "procedure": procedure, "estimate": settled, "appointment": completed,
    }


def setup_issued_with_dispute_under_review(api, disputed_amount_cents=5000):
    """Issued insured estimate (PR 122500) with a dispute in UNDER_REVIEW.
    Returns a bundle including estimate and dispute."""
    b = setup_insured_issued_single_line(api, set_clock_first=True)
    dispute = file_dispute(api, b["estimate"]["id"], b["patient"]["id"],
                           disputed_amount_cents=disputed_amount_cents)
    assign_dispute(api, dispute["id"])
    b["dispute"] = get_success_data(api.get_dispute(dispute["id"], PROVIDER))
    b["estimate"] = get_success_data(api.get_estimate(b["estimate"]["id"], PROVIDER))
    return b


def three_active_flat_rates(api, procedure_id, amounts):
    """Create len(amounts) distinct ACTIVE contracts, each with a FLAT rate for
    procedure_id. Used by shoppable-comparison scenarios."""
    contracts = []
    for i, amt in enumerate(amounts):
        contract = new_active_contract(api, payer_name=f"Payer{i + 1}")
        ingest_flat_rate(api, contract["id"], procedure_id, amt)
        contracts.append(contract)
    return contracts
