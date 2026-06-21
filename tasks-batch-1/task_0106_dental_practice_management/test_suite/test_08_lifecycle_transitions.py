"""State-machine preconditions, side effects, terminal lockdown, and clock-driven
transitions.

Corner queue B: state_machines section instances.
"""
from test_helpers import (
    setup_practice,
    create_patient,
    create_provider,
    create_plan_with_items,
    propose_plan,
    accept_plan,
    complete_item_via_visit,
    book_appointment,
    create_claim,
    create_predetermination,
    create_payment_plan,
    setup_adjudicated_claim,
    set_clock,
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


def test_propose_empty_plan_returns_plan_has_no_items():
    """PRD §3.3: "Proposing the plan advances it from `DRAFT` to `PROPOSED`. This
    requires the plan to be in `DRAFT` (otherwise `ERR_INVALID_STATE`) and to hold
    at least one item in `PLANNED` status (otherwise `ERR_PLAN_HAS_NO_ITEMS`)."

    Design: Corner/state_machines/propose_empty_plan_returns_plan_has_no_items
    """
    ctx = setup_practice(with_coverage=False)
    clin = ctx["clinician_headers"]
    plan = get_success_data(api_client.create_treatment_plan(
        {"patient_id": ctx["patient"]["id"], "provider_id": ctx["provider"]["id"]}, clin))
    resp = api_client.propose_treatment_plan(plan["id"], clin)
    validate_error(resp, ApiErrorId.ERR_PLAN_HAS_NO_ITEMS.value)
    plan_after = validate_success(api_client.get_treatment_plan(plan["id"], clin))
    assert plan_after["status"] == "DRAFT"


def test_accept_from_draft_invalid_state():
    """PRD §3.3: "Acceptance is a `FrontDesk` action that moves the plan from
    `PROPOSED` to `ACCEPTED`; it requires the plan to be in `PROPOSED` (otherwise
    `ERR_INVALID_STATE`)".

    Design: Corner/state_machines/accept_from_draft_invalid_state
    """
    ctx = setup_practice(with_coverage=False)
    plan, _ = create_plan_with_items(
        ctx["patient"]["id"], ctx["provider"]["id"],
        [{"cdt_code": "D1110", "category": "PREVENTIVE", "fee_cents": 12_000, "phase_number": 1}],
    )
    resp = api_client.accept_treatment_plan(plan["id"], FD)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_complete_plan_with_incomplete_items_rejected():
    """PRD §3.3: "Completing a plan is a `Clinician` action moving it from
    `ACCEPTED` to `COMPLETED`; it requires the plan to be `ACCEPTED` (otherwise
    `ERR_INVALID_STATE`) and every non-`CANCELLED` item to be `COMPLETED`
    (otherwise `ERR_PLAN_ITEMS_NOT_COMPLETE`)."

    Design: Corner/state_machines/complete_plan_with_incomplete_items_rejected
    """
    ctx = setup_practice(with_coverage=False)
    plan, _ = create_plan_with_items(
        ctx["patient"]["id"], ctx["provider"]["id"],
        [{"cdt_code": "D1110", "category": "PREVENTIVE", "fee_cents": 12_000, "phase_number": 1}],
    )
    propose_plan(plan["id"], ctx["provider"]["id"])
    accept_plan(plan["id"])
    resp = api_client.complete_treatment_plan(plan["id"], ctx["clinician_headers"])
    validate_error(resp, ApiErrorId.ERR_PLAN_ITEMS_NOT_COMPLETE.value)


def test_appointment_cancel_releases_item_to_planned():
    """PRD §3.4: "In both cancellation and no-show, if the linked item is
    `SCHEDULED` it is released back to `PLANNED` and its `appointment_id` is
    cleared, freeing the slot."

    Design: Corner/state_machines/appointment_cancel_releases_item_to_planned
    """
    ctx = setup_practice(with_coverage=False)
    patient, provider, operatory = ctx["patient"], ctx["provider"], ctx["operatory"]
    plan, items = create_plan_with_items(
        patient["id"], provider["id"],
        [{"cdt_code": "D1110", "category": "PREVENTIVE", "fee_cents": 12_000, "phase_number": 1}],
    )
    item = items[0]
    propose_plan(plan["id"], provider["id"])
    accept_plan(plan["id"])
    appt = book_appointment(patient["id"], provider["id"], operatory["id"],
                            treatment_plan_item_id=item["id"], appointment_type="PREVENTIVE",
                            start_at="2026-03-10T09:00:00Z", end_at="2026-03-10T09:45:00Z")
    cancelled = validate_success(api_client.cancel_appointment(appt["id"], FD))
    assert cancelled["status"] == "CANCELLED"
    item_after = validate_success(
        api_client.get_treatment_plan_item(item["id"], ctx["clinician_headers"]))
    assert item_after["status"] == "PLANNED"
    assert item_after.get("appointment_id") is None


def test_appointment_complete_bubbles_item_to_completed():
    """PRD §3.4: "A `Clinician` completes the visit, moving it from `CHECKED_IN` to
    `COMPLETED`; this requires the appointment to be `CHECKED_IN` ... and if the
    appointment has a `treatment_plan_item_id` whose item is `SCHEDULED`, that item
    bubbles up to `COMPLETED`."

    Design: Corner/state_machines/appointment_complete_bubbles_item_to_completed
    """
    ctx = setup_practice(with_coverage=False)
    patient, provider, operatory = ctx["patient"], ctx["provider"], ctx["operatory"]
    clin = ctx["clinician_headers"]
    plan, items = create_plan_with_items(
        patient["id"], provider["id"],
        [{"cdt_code": "D1110", "category": "PREVENTIVE", "fee_cents": 12_000, "phase_number": 1}],
    )
    item = items[0]
    propose_plan(plan["id"], provider["id"])
    accept_plan(plan["id"])
    appt = book_appointment(patient["id"], provider["id"], operatory["id"],
                            treatment_plan_item_id=item["id"], appointment_type="PREVENTIVE",
                            start_at="2026-03-11T09:00:00Z", end_at="2026-03-11T09:45:00Z")
    validate_success(api_client.check_in_appointment(appt["id"], FD))
    completed = validate_success(api_client.complete_appointment(appt["id"], clin))
    assert completed["status"] == "COMPLETED"
    item_after = validate_success(api_client.get_treatment_plan_item(item["id"], clin))
    assert item_after["status"] == "COMPLETED"


def test_terminal_appointment_cannot_check_in():
    """PRD §3.4: "a no-show moves it to `NO_SHOW` and is permitted only from
    `SCHEDULED` (otherwise `ERR_INVALID_STATE`)."
    PRD §3.4: "this requires the appointment to be `SCHEDULED` (otherwise
    `ERR_INVALID_STATE`)" (check-in).

    A NO_SHOW (terminal) appointment cannot be checked in: ERR_INVALID_STATE.

    Design: Corner/state_machines/terminal_appointment_cannot_check_in
    """
    ctx = setup_practice(with_coverage=False)
    patient, provider, operatory = ctx["patient"], ctx["provider"], ctx["operatory"]
    appt = book_appointment(patient["id"], provider["id"], operatory["id"],
                            appointment_type="OPERATIVE",
                            start_at="2026-03-12T09:00:00Z", end_at="2026-03-12T10:00:00Z")
    validate_success(api_client.no_show_appointment(appt["id"], FD))
    resp = api_client.check_in_appointment(appt["id"], FD)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_predetermination_deny_is_terminal():
    """PRD §3.5: "A `BillingSpecialist` may instead deny a `PENDING`
    predetermination, moving it to `DENIED` (from any other state,
    `ERR_INVALID_STATE`)."
    PRD §3.5: "it is permitted when the predetermination is `PENDING`, and also when
    it is `REQUIRES_REVALIDATION` ... from any other state it is rejected with
    `ERR_INVALID_STATE`." (approve)

    Approving a DENIED (terminal) predetermination is rejected with
    ERR_INVALID_STATE.

    Design: Corner/state_machines/predetermination_deny_is_terminal
    """
    ctx = setup_practice()
    patient, provider, coverage = ctx["patient"], ctx["provider"], ctx["coverage"]
    clin = ctx["clinician_headers"]
    plan = get_success_data(api_client.create_treatment_plan(
        {"patient_id": patient["id"], "provider_id": provider["id"]}, clin))
    item = get_success_data(api_client.add_treatment_plan_item(
        plan["id"], {"cdt_code": "D2740", "category": "MAJOR", "fee_cents": 90_000,
                     "phase_number": 1, "tooth_number": 8}, clin))
    pred = create_predetermination(item["id"], coverage["id"])
    validate_success(api_client.deny_predetermination(pred["id"], BILL))
    resp = api_client.approve_predetermination(
        pred["id"], {"approved_benefit_cents": 42_500, "valid_until_date": "2027-01-01"}, BILL)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_claim_submit_without_attachment_rejected():
    """PRD §3.6: "Submitting the claim, a `BillingSpecialist` action, advances
    `submission_status` from `DRAFT` to `SUBMITTED`; it requires the claim to be in
    `DRAFT` submission status (otherwise `ERR_INVALID_STATE`) and at least one
    attachment to exist (otherwise `ERR_CLAIM_MISSING_ATTACHMENT`)."

    Design: Corner/state_machines/claim_submit_without_attachment_rejected
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
                            start_at="2026-03-13T09:00:00Z", end_at="2026-03-13T10:00:00Z")
    claim = create_claim(patient["id"], item["id"], coverage["id"])
    resp = api_client.submit_claim(claim["id"], BILL)
    validate_error(resp, ApiErrorId.ERR_CLAIM_MISSING_ATTACHMENT.value)


def test_claim_adjudicate_before_submit_rejected():
    """PRD §3.6: "A `BillingSpecialist` adjudicates a submitted claim; this requires
    `submission_status` to be `SUBMITTED` (otherwise `ERR_CLAIM_NOT_SUBMITTED`)".

    Design: Corner/state_machines/claim_adjudicate_before_submit_rejected
    """
    ctx = setup_practice()
    patient, provider, operatory, coverage = (
        ctx["patient"], ctx["provider"], ctx["operatory"], ctx["coverage"]
    )
    plan, items = create_plan_with_items(
        patient["id"], provider["id"],
        [{"cdt_code": "D2160", "category": "BASIC", "fee_cents": 45_000,
          "phase_number": 1, "tooth_number": 6}],
    )
    item = items[0]
    propose_plan(plan["id"], provider["id"])
    accept_plan(plan["id"])
    complete_item_via_visit(patient["id"], provider["id"], operatory["id"], item["id"],
                            start_at="2026-03-14T09:00:00Z", end_at="2026-03-14T10:00:00Z")
    claim = create_claim(patient["id"], item["id"], coverage["id"])
    resp = api_client.adjudicate_claim(claim["id"], BILL)
    validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_SUBMITTED.value)


def test_void_claim_with_active_payment_plan_rejected():
    """PRD §3.6: "A `BillingSpecialist` voids a claim, moving `adjudication_status`
    to `VOID`; this is permitted only when the claim is `PAID` or `PARTIALLY_PAID`
    (otherwise `ERR_CLAIM_NOT_VOIDABLE`) and only when no `ACTIVE` payment plan
    references the claim (otherwise `ERR_CLAIM_HAS_ACTIVE_PAYMENT_PLAN`)."

    Design: Corner/state_machines/void_claim_with_active_payment_plan_rejected
    """
    ctx = setup_practice()
    _, claim = setup_adjudicated_claim(ctx, 120_000, category="MAJOR", cdt_code="D2740",
                                       tooth_number=8, document_ref="ref://vpp",
                                       attachment_type="XRAY")
    create_payment_plan(ctx["patient"]["id"], claim["id"], claim["version"], installment_count=5)
    resp = api_client.void_claim(claim["id"], BILL)
    validate_error(resp, ApiErrorId.ERR_CLAIM_HAS_ACTIVE_PAYMENT_PLAN.value)


def test_recare_recall_becomes_due_on_clock_advance():
    """PRD §3.7: "The system computes `next_due_date` as the `last_visit_date` plus
    `interval_months` of calendar time, and opens the recall in `ACTIVE` ... When
    the logical clock reaches or passes a recall's `next_due_date`, the recall
    flips from `ACTIVE` to `DUE`."

    last_visit 2026-01-15 + 6 months => next_due 2026-07-15; clock set to
    2026-07-15 flips status ACTIVE->DUE (>= boundary).

    Design: Corner/state_machines/recare_recall_becomes_due_on_clock_advance
    """
    patient = create_patient(full_name="Rec Pat")
    rec = validate_success(api_client.create_recare_recall(
        {"patient_id": patient["id"], "recall_type": "PROPHY", "interval_months": 6,
         "last_visit_date": "2026-01-15"}, FD), expected_status=201)
    assert rec["next_due_date"] == "2026-07-15"
    set_clock("2026-07-15T00:00:00Z", FD)
    rec_after = validate_success(api_client.get_recare_recall(rec["id"], FD))
    assert rec_after["status"] == "DUE"
