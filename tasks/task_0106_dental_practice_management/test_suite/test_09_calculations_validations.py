"""Estimate calculations, business validations, and the immediate-consistency
read-after-write.

Corner queue B: calculations, validations, endpoints, consistency_model,
cross_cutting_complexity_layers, errors sections.
"""
from test_helpers import (
    setup_practice,
    create_patient,
    create_provider,
    create_plan_with_items,
    propose_plan,
    accept_plan,
    complete_item_via_visit,
    create_claim,
    attach_and_submit,
    adjudicate_claim,
    setup_adjudicated_claim,
    create_payment_plan,
    validate_success,
    get_success_data,
    validate_error,
    ApiErrorId,
    make_clinician_headers,
    TEST_USERS,
)
from test_helpers import api_client

FD = TEST_USERS["front_desk_headers"]
BILL = TEST_USERS["billing_headers"]


# ─── calculations ─────────────────────────────────────────────────────────────

def test_estimate_preventive_applies_deductible():
    """PRD §3.8: "It computes the remaining deductible as the plan's
    `deductible_cents` minus the coverage's current `deductible_met_cents`, floored
    at zero; the deductible applied is the smaller of that remaining deductible and
    the item's `fee_cents`; and the amount after deductible is the item's
    `fee_cents` minus the deductible applied. The gross benefit is the amount after
    deductible multiplied by the chosen coinsurance percentage, divided by 100".

    A fresh PREVENTIVE item fee=12000 (100% coinsurance, deductible 5000):
    after_ded=7000, gross=7000, estimate=7000, patient portion=5000.

    Design: Corner/calculations/estimate_preventive_full_coverage_zero_patient_portion
    """
    ctx = setup_practice()
    patient, provider = ctx["patient"], ctx["provider"]
    plan, items = create_plan_with_items(
        patient["id"], provider["id"],
        [{"cdt_code": "D1110", "category": "PREVENTIVE", "fee_cents": 12_000, "phase_number": 1}],
    )
    item = items[0]
    propose_plan(plan["id"], provider["id"])
    after = validate_success(api_client.get_treatment_plan_item(item["id"], ctx["clinician_headers"]))
    assert after["estimated_insurance_cents"] == 7000
    assert after["estimated_patient_portion_cents"] == 5000


def test_estimate_zero_when_no_active_coverage():
    """PRD §3.8: "The system selects the patient's coverage as the `ACTIVE`
    `PatientCoverage` with the latest `coverage_start_date`, breaking ties by the
    earliest `created_at`; if the patient has no active coverage, the item's
    `estimated_insurance_cents` is zero."

    Design: Corner/calculations/estimate_zero_when_no_active_coverage
    """
    ctx = setup_practice(with_coverage=False)
    patient, provider = ctx["patient"], ctx["provider"]
    plan, items = create_plan_with_items(
        patient["id"], provider["id"],
        [{"cdt_code": "D2150", "category": "BASIC", "fee_cents": 40_000,
          "phase_number": 1, "tooth_number": 5}],
    )
    item = items[0]
    propose_plan(plan["id"], provider["id"])
    after = validate_success(api_client.get_treatment_plan_item(item["id"], ctx["clinician_headers"]))
    assert after["estimated_insurance_cents"] == 0
    assert after["estimated_patient_portion_cents"] == 40000


def test_claim_denied_makes_patient_responsible_for_full_fee():
    """PRD §3.6: "A carrier denial ... sets `carrier_paid_cents` to zero and
    `patient_responsibility_cents` to the full `billed_fee_cents`".

    A submitted BASIC claim fee=50000 denied => carrier_paid 0, patient
    responsibility 50000.

    Design: Corner/calculations/claim_denied_makes_patient_responsible_for_full_fee
    """
    ctx = setup_practice()
    patient, provider, operatory, coverage = (
        ctx["patient"], ctx["provider"], ctx["operatory"], ctx["coverage"]
    )
    plan, items = create_plan_with_items(
        patient["id"], provider["id"],
        [{"cdt_code": "D2393", "category": "BASIC", "fee_cents": 50_000,
          "phase_number": 1, "tooth_number": 20}],
    )
    item = items[0]
    propose_plan(plan["id"], provider["id"])
    accept_plan(plan["id"])
    complete_item_via_visit(patient["id"], provider["id"], operatory["id"], item["id"],
                            start_at="2026-03-16T09:00:00Z", end_at="2026-03-16T10:00:00Z")
    claim = create_claim(patient["id"], item["id"], coverage["id"])
    attach_and_submit(claim["id"], attachment_type="NARRATIVE", document_ref="ref://deny")
    denied = validate_success(api_client.deny_claim(claim["id"], BILL))
    assert denied["carrier_paid_cents"] == 0
    assert denied["patient_responsibility_cents"] == 50000


# ─── validations ──────────────────────────────────────────────────────────────

def test_hygienist_cannot_own_operative_appointment():
    """PRD §3.4: "A `HYGIENIST` provider may own only `PREVENTIVE` appointments;
    assigning one to an `OPERATIVE` appointment is rejected with
    `ERR_PROVIDER_TYPE_MISMATCH`."

    Design: Corner/validations/hygienist_cannot_own_operative_appointment
    """
    patient = create_patient()
    hyg = create_provider(provider_type="HYGIENIST")
    operatory = validate_success(api_client.create_operatory({"room_name": "OP-H"}, FD), expected_status=201)
    resp = api_client.create_appointment(
        {"patient_id": patient["id"], "provider_id": hyg["id"], "operatory_id": operatory["id"],
         "appointment_type": "OPERATIVE", "start_at": "2026-03-17T09:00:00Z",
         "end_at": "2026-03-17T10:00:00Z"}, FD)
    validate_error(resp, ApiErrorId.ERR_PROVIDER_TYPE_MISMATCH.value)


def test_predetermination_annual_max_reached_blocks_create():
    """PRD §3.5: "if the coverage's annual maximum has already been reached,
    requesting a benefit-bearing predetermination is rejected with
    `ERR_ANNUAL_MAX_REACHED` (HTTP 402)."

    After a BASIC claim pays exactly 100000 (annual_max_reached true), a new
    predetermination for a MAJOR item is rejected with ERR_ANNUAL_MAX_REACHED.

    Design: Corner/validations/predetermination_annual_max_reached_blocks_create
    """
    ctx = setup_practice()
    patient, provider, operatory, coverage = (
        ctx["patient"], ctx["provider"], ctx["operatory"], ctx["coverage"]
    )
    clin = ctx["clinician_headers"]
    plan = get_success_data(api_client.create_treatment_plan(
        {"patient_id": patient["id"], "provider_id": provider["id"]}, clin))
    big = get_success_data(api_client.add_treatment_plan_item(
        plan["id"], {"cdt_code": "D2397", "category": "BASIC", "fee_cents": 130_000,
                     "phase_number": 1, "tooth_number": 13}, clin))
    major = get_success_data(api_client.add_treatment_plan_item(
        plan["id"], {"cdt_code": "D2740", "category": "MAJOR", "fee_cents": 90_000,
                     "phase_number": 1, "tooth_number": 8}, clin))
    propose_plan(plan["id"], provider["id"])
    accept_plan(plan["id"])
    complete_item_via_visit(patient["id"], provider["id"], operatory["id"], big["id"],
                            start_at="2026-03-18T09:00:00Z", end_at="2026-03-18T10:00:00Z")
    claim = create_claim(patient["id"], big["id"], coverage["id"])
    attach_and_submit(claim["id"], attachment_type="XRAY", document_ref="ref://max")
    adjudicate_claim(claim["id"])
    resp = api_client.create_predetermination(
        {"treatment_plan_item_id": major["id"], "patient_coverage_id": coverage["id"]}, BILL)
    validate_error(resp, ApiErrorId.ERR_ANNUAL_MAX_REACHED.value)


def test_claim_create_on_incomplete_item_rejected():
    """PRD §3.6: "The item must be `COMPLETED` before a claim may be created, or the
    request is rejected with `ERR_ITEM_NOT_COMPLETED`".

    An ACCEPTED plan with a still-PLANNED item (coverage belongs to the same
    patient so the referential check passes): creating a claim is rejected with
    ERR_ITEM_NOT_COMPLETED.

    Design: Corner/validations/claim_create_on_incomplete_item_rejected
    """
    ctx = setup_practice()
    patient, provider, coverage = ctx["patient"], ctx["provider"], ctx["coverage"]
    plan, items = create_plan_with_items(
        patient["id"], provider["id"],
        [{"cdt_code": "D2150", "category": "BASIC", "fee_cents": 40_000,
          "phase_number": 1, "tooth_number": 5}],
    )
    item = items[0]
    propose_plan(plan["id"], provider["id"])
    accept_plan(plan["id"])
    resp = api_client.create_claim(
        {"patient_id": patient["id"], "treatment_plan_item_id": item["id"],
         "patient_coverage_id": coverage["id"]}, BILL)
    validate_error(resp, ApiErrorId.ERR_ITEM_NOT_COMPLETED.value)


# ─── endpoints ────────────────────────────────────────────────────────────────

def test_fk_filtered_list_claims_by_patient():
    """PRD §4: "GET `/claims` List claims".
    PRD §3.6: "A `BillingSpecialist` creates a claim with a `patient_id`, a
    `treatment_plan_item_id`, and a `patient_coverage_id`."

    Filtering GET /claims by patient_id returns only that patient's claims.

    Design: Corner/endpoints/fk_filtered_list_claims_by_patient
    """
    ctx = setup_practice()
    patient, provider, operatory, coverage = (
        ctx["patient"], ctx["provider"], ctx["operatory"], ctx["coverage"]
    )
    plan, items = create_plan_with_items(
        patient["id"], provider["id"],
        [{"cdt_code": "D2150", "category": "BASIC", "fee_cents": 40_000,
          "phase_number": 1, "tooth_number": 5}],
    )
    item = items[0]
    propose_plan(plan["id"], provider["id"])
    accept_plan(plan["id"])
    complete_item_via_visit(patient["id"], provider["id"], operatory["id"], item["id"],
                            start_at="2026-03-19T09:00:00Z", end_at="2026-03-19T10:00:00Z")
    claim = create_claim(patient["id"], item["id"], coverage["id"])
    resp = api_client.list_claims(BILL, params={"patient_id": patient["id"]})
    from test_helpers import validate_paginated
    data, _ = validate_paginated(resp)
    ids = [c["id"] for c in data]
    assert claim["id"] in ids
    assert all(c["patient_id"] == patient["id"] for c in data)


# ─── errors ───────────────────────────────────────────────────────────────────

def test_appointment_end_before_start_validation():
    """PRD §3.4: "The `appointment_type` is either `PREVENTIVE` or `OPERATIVE`, and
    `end_at` must be strictly later than `start_at`."

    Booking with end_at <= start_at fails body validation with ERR_VALIDATION.

    Design: Corner/errors/appointment_end_before_start_validation
    """
    patient = create_patient()
    provider = create_provider(provider_type="DENTIST")
    operatory = validate_success(api_client.create_operatory({"room_name": "OP-W"}, FD), expected_status=201)
    resp = api_client.create_appointment(
        {"patient_id": patient["id"], "provider_id": provider["id"], "operatory_id": operatory["id"],
         "appointment_type": "OPERATIVE", "start_at": "2026-03-23T10:00:00Z",
         "end_at": "2026-03-23T09:00:00Z"}, FD)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


# ─── consistency_model ────────────────────────────────────────────────────────

def test_adjudicate_cascade_visible_in_same_request():
    """PRD §3.6: "at depth one the coverage's `annual_benefit_used_cents` is
    increased by `carrier_paid_cents`".
    PRD §2.9: "Retrieving a coverage shows its live accumulators." (§3.2)

    A BASIC claim fee=50000 adjudicates to 36000; an immediately following GET on
    the coverage already shows annual_benefit_used_cents == 36000.

    Design: Corner/consistency_model/adjudicate_cascade_visible_in_same_request
    """
    ctx = setup_practice()
    _, claim = setup_adjudicated_claim(ctx, 50_000, category="BASIC", cdt_code="D2393",
                                       tooth_number=20, document_ref="ref://imm",
                                       attachment_type="XRAY")
    assert claim["carrier_paid_cents"] == 36000
    cov = validate_success(api_client.get_patient_coverage(ctx["coverage"]["id"], BILL))
    assert cov["annual_benefit_used_cents"] == 36000


# ─── cross_cutting_complexity_layers ──────────────────────────────────────────

def test_occ_stale_claim_version_rejected():
    """PRD §2.7: "The server compares it to the claim's current `version`; if they
    do not match, the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and
    no payment plan is created."
    PRD §2.7: "creating a payment plan against a claim increments that claim's
    `version` by one."

    After the first payment plan bumps the claim version, a second create reusing
    the pre-bump version is rejected with ERR_STALE_VERSION.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_claim_version_negative_rejected
    """
    ctx = setup_practice()
    _, claim = setup_adjudicated_claim(ctx, 120_000, category="MAJOR", cdt_code="D2740",
                                       tooth_number=8, document_ref="ref://occ",
                                       attachment_type="XRAY")
    stale_version = claim["version"]
    create_payment_plan(ctx["patient"]["id"], claim["id"], stale_version, installment_count=5)
    resp = api_client.create_payment_plan(
        {"patient_id": ctx["patient"]["id"], "claim_id": claim["id"],
         "installment_count": 7, "expected_claim_version": stale_version}, BILL)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_derived_balance_owed_reconciliation_after_deny():
    """PRD §3.1: "A patient's `balance_owed_cents` is a running total of the
    `patient_responsibility_cents` across that patient's claims that are not yet
    covered by an active payment plan, recomputed whenever a claim is adjudicated,
    denied, or voided".
    PRD §3.6: "A carrier denial ... sets `carrier_paid_cents` to zero and
    `patient_responsibility_cents` to the full `billed_fee_cents`, and recomputes
    the patient's `balance_owed_cents`."

    After denying a BASIC claim fee=50000, the patient's balance_owed_cents rises
    to the full 50000.

    Design: Corner/cross_cutting_complexity_layers/derived_balance_owed_reconciliation_after_deny
    """
    ctx = setup_practice()
    patient, provider, operatory, coverage = (
        ctx["patient"], ctx["provider"], ctx["operatory"], ctx["coverage"]
    )
    plan, items = create_plan_with_items(
        patient["id"], provider["id"],
        [{"cdt_code": "D2393", "category": "BASIC", "fee_cents": 50_000,
          "phase_number": 1, "tooth_number": 20}],
    )
    item = items[0]
    propose_plan(plan["id"], provider["id"])
    accept_plan(plan["id"])
    complete_item_via_visit(patient["id"], provider["id"], operatory["id"], item["id"],
                            start_at="2026-03-22T09:00:00Z", end_at="2026-03-22T10:00:00Z")
    claim = create_claim(patient["id"], item["id"], coverage["id"])
    attach_and_submit(claim["id"], attachment_type="NARRATIVE", document_ref="ref://bal")
    validate_success(api_client.deny_claim(claim["id"], BILL))
    patient_after = validate_success(api_client.get_patient(patient["id"], BILL))
    assert patient_after["balance_owed_cents"] == 50000
