"""State-transition guards, referral continuity, cancellation side effects, and
calculation corner cases (deposit tiers, non-promo plan, 2-night board).

Corner queue: state_machines, calculations sections.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    make_triage_nurse_headers,
    make_clinician_dvm_headers,
    make_finance_coordinator_headers,
    register_patient,
    register_visit,
    register_and_triage,
    create_draft_estimate,
    setup_visit_with_active_hospitalization,
    setup_finalized_invoice,
    get_invoice,
    api_client,
)


# ---- state_machines ----

def test_triage_already_triaged_invalid_state(api):
    """PRD §3.2: "a `TriageNurse` assigns urgency by triaging it, which requires
    the Visit to be in `REGISTERED` status (otherwise `ERR_INVALID_STATE`)"

    Design: Corner/state_machines/triage_from_already_triaged_returns_invalid_state
    """
    nurse = make_triage_nurse_headers()
    _, visit = register_and_triage(triage_level="YELLOW", owner_user_id="owner-1")
    resp = api.triage_visit(visit["id"], {"triage_level": "RED"}, nurse)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_begin_treatment_from_registered_invalid_state(api):
    """PRD §3.6: "A `ClinicianDVM` begins treatment on a Visit that is in
    `TRIAGED` status (`ERR_INVALID_STATE`)"

    Design: Corner/state_machines/begin_treatment_from_registered_returns_invalid_state
    """
    nurse = make_triage_nurse_headers()
    dvm = make_clinician_dvm_headers()
    patient = register_patient(owner_user_id="owner-1")
    visit = register_visit(patient["id"])
    resp = api.begin_treatment(visit["id"], dvm)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_accept_declined_referral_invalid_state(api):
    """PRD §3.3: "Accepting requires the Referral to be `PENDING`
    (`ERR_INVALID_STATE`) and the parent Visit to be in either `TRIAGED` or
    `IN_TREATMENT` status"
    PRD §3.3: "Both `ACCEPTED` and `DECLINED` are terminal for a referral."

    Design: Corner/state_machines/referral_accept_from_declined_returns_invalid_state
    """
    dvm = make_clinician_dvm_headers()
    _, visit = register_and_triage(triage_level="YELLOW", owner_user_id="owner-1",
                                   chief_complaint="cardiac")
    ref = validate_success(api.create_referral(visit["id"], {
        "to_department": "CARDIOLOGY", "accepting_dvm_id": "dvm-cardio",
        "reason": "murmur"}, dvm), expected_status=201)
    validate_success(api.decline_referral(visit["id"], ref["id"], dvm))
    resp = api.accept_referral(visit["id"], ref["id"], dvm)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_accept_referral_transfers_department_and_dvm(api):
    """PRD §3.3: "Acceptance moves the Referral from `PENDING` to `ACCEPTED` and,
    in the same operation, transfers the case: the Visit's `department` is set to
    the referral's `to_department` and the Visit's `attending_dvm_id` is set to
    the referral's `accepting_dvm_id`."

    Design: Corner/state_machines/referral_accept_transfers_department_and_dvm
    """
    dvm = make_clinician_dvm_headers()
    _, visit = register_and_triage(triage_level="YELLOW", owner_user_id="owner-1",
                                   chief_complaint="cardiac")
    ref = validate_success(api.create_referral(visit["id"], {
        "to_department": "CARDIOLOGY", "accepting_dvm_id": "dvm-cardio",
        "reason": "murmur"}, dvm), expected_status=201)
    accepted = validate_success(api.accept_referral(visit["id"], ref["id"], dvm))
    assert accepted["status"] == "ACCEPTED"
    v = validate_success(api.get_visit(visit["id"], dvm))
    assert v["department"] == "CARDIOLOGY"
    assert v["attending_dvm_id"] == "dvm-cardio"


def test_hospitalization_cancel_frees_cage_no_charge(api):
    """PRD §3.7: "A hospitalization may instead be cancelled by a `ClinicianDVM`
    while `ACTIVE` (`ERR_INVALID_STATE`); cancellation posts no board charge,
    frees the cage, moves the hospitalization from `ACTIVE` to `CANCELLED`, and
    increments the Hospitalization's and Visit's `version`."

    Design: Corner/state_machines/hospitalization_cancel_frees_cage_no_charge
    """
    dvm = make_clinician_dvm_headers()
    _, visit, est, auth, hosp = setup_visit_with_active_hospitalization(
        triage_level="YELLOW", ward="ICU", cage_number=1,
        admit_at="2026-05-01T08:00:00Z",
        planned_discharge_at="2026-05-02T08:00:00Z",
        approved_ceiling_cents=300000, owner_user_id="owner-1")
    resp = api.cancel_hospitalization(visit["id"], hosp["id"], dvm)
    cancelled = validate_success(resp)
    assert cancelled["status"] == "CANCELLED"
    invoice = get_invoice(visit["id"])
    assert invoice["subtotal_cents"] == 0, (
        f"cancellation posts no board charge, subtotal must be 0, got {invoice['subtotal_cents']}")


# ---- calculations ----

def test_estimate_red_tier_deposit(api):
    """PRD §3.4: "The `deposit_pct` is 0.80 for a `RED` case, 0.60 for `ORANGE`,
    0.50 for `YELLOW`, and 0.30 for `GREEN`. The `deposit_cents` is `high_cents`
    multiplied by `deposit_pct`, rounded up to the next whole cent."

    Design: Corner/calculations/estimate_red_tier_deposit_correct
    """
    _, visit = register_and_triage(triage_level="RED", owner_user_id="owner-1",
                                   chief_complaint="arrest")
    est = create_draft_estimate(visit["id"], unit_price_cents=300000)
    assert est["high_cents"] == 386100, f"expected high_cents 386100, got {est['high_cents']}"
    assert est["deposit_pct"] == 0.8
    assert est["deposit_cents"] == 308880, f"expected 308880, got {est['deposit_cents']}"


def test_payment_plan_no_promo_when_term_over_max(api):
    """PRD §3.10: "`promo_applied` is true if and only if the provider is
    `CARECREDIT` and the `principal_cents` is at least 100,000 cents and the
    `term_months` is at most 6; if any of those three conditions fails, no
    promotion applies."
    PRD §3.10: "otherwise the `financing_fee_cents` is the principal multiplied by
    the monthly rate of 0.0225 multiplied by the number of `term_months`, rounded
    up to the next whole cent."

    Design: Corner/calculations/payment_plan_no_promo_when_term_over_max
    """
    finance = make_finance_coordinator_headers()
    _, visit, _, _, _, invoice = setup_finalized_invoice(
        surgery_price=300000, triage_level="YELLOW",
        approved_ceiling_cents=386100, owner_user_id="owner-3")
    resp = api.create_payment_plan(visit["id"], {
        "invoice_id": invoice["id"], "provider": "CARECREDIT", "term_months": 12,
    }, finance)
    plan = validate_success(resp, expected_status=201)
    assert plan["promo_applied"] is False
    assert plan["financing_fee_cents"] == 34749, (
        f"expected fee 34749, got {plan['financing_fee_cents']}")
    assert plan["installment_cents"] == 13621
    assert plan["final_installment_cents"] == 13618


def test_icu_board_two_nights_accrual(api):
    """PRD §3.7: "The nights are the elapsed time from `admit_at` to `released_at`
    measured in hours, divided by 24 and rounded up to a whole number ... The
    board charge is the accrued nights multiplied by the per-diem for the ward:
    an ICU night is 180,000 cents and a general ward night is 60,000 cents."
    PRD §3.7: "This board charge is appended as a charge line to the Visit's open
    invoice, the invoice's subtotal, tax, and balance are recomputed"

    Design: Corner/calculations/icu_board_two_nights_accrual
    """
    dvm = make_clinician_dvm_headers()
    _, visit, est, auth, hosp = setup_visit_with_active_hospitalization(
        triage_level="YELLOW", ward="ICU", cage_number=1,
        admit_at="2026-05-01T08:00:00Z",
        planned_discharge_at="2026-05-03T08:00:00Z",
        approved_ceiling_cents=600000, owner_user_id="owner-1")
    resp = api.release_hospitalization(visit["id"], hosp["id"],
                                       {"released_at": "2026-05-03T08:00:00Z"}, dvm)
    released = validate_success(resp)
    assert released["nights_accrued"] == 2, f"expected 2 nights, got {released['nights_accrued']}"
    assert released["board_cents"] == 360000, f"expected 360000, got {released['board_cents']}"
    invoice = get_invoice(visit["id"])
    assert invoice["subtotal_cents"] == 360000
