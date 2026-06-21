"""Fill workflow transitions, DUR screening, prescription lifecycle.

Translations of SCAFFOLD_CORNER_DESIGN.yaml §1.9 `state_machines` and the
DUR-severity `calculations` instances.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    submit_claim_payload, create_payment_record_payload,
)
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["admin_headers"]
TECH = TEST_USERS["technician_headers"]
PHARM = TEST_USERS["pharmacist_headers"]
CASH = TEST_USERS["cashier_headers"]


def test_prescription_initial_state_active(api):
    """PRD §3.3: "At intake the prescription enters `ACTIVE` status, its
    `refills_remaining` is set equal to `refills_authorized`".

    Design: Corner/state_machines/prescription_initial_state_active
    """
    fx.set_clock()
    drug = fx.create_drug(ndc="77777-0004-01", name="InitDrug", unit_price_cents=500)
    patient = fx.create_patient(full_name="Init P", date_of_birth="1980-01-01")
    prescriber = fx.create_prescriber(full_name="Dr Init", npi="2000000013")
    resp = api.create_prescription(
        {"patient_id": patient["id"], "prescriber_id": prescriber["id"],
         "drug_id": drug["id"], "quantity_per_fill": 10, "days_supply": 30,
         "refills_authorized": 3, "written_utc": "2026-01-01T00:00:00.000Z"},
        TECH,
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "ACTIVE"
    assert data["refills_remaining"] == 3


def test_dur_severity_none_auto_advances_to_adjudicating(api):
    """PRD §3.4: "if no alerts were raised the `dur_severity` is `NONE` and the
    fill auto-advances from `ENTERED` straight through `DUR_REVIEW` to
    `ADJUDICATING`".

    Design: Corner/state_machines/dur_severity_none_auto_advances_to_adjudicating
    """
    fx.set_clock()
    drug = fx.create_drug(ndc="77777-0007-01", name="CleanDrug", unit_price_cents=500)
    patient = fx.create_patient(full_name="Clean P", date_of_birth="1980-01-01")
    prescriber = fx.create_prescriber(full_name="Dr Clean", npi="2000000016")
    rx = fx.create_prescription(patient["id"], prescriber["id"], drug["id"],
                                quantity_per_fill=30, days_supply=30)
    fill = fx.create_fill(rx["id"])
    resp = api.run_dur(fill["id"], TECH)
    data = validate_success(resp)
    assert data["dur_severity"] == "NONE"
    assert data["status"] == "ADJUDICATING"


def test_dur_high_dose_moderate_severity(api):
    """PRD §3.5: "if the fill's `quantity_dispensed` divided by its `days_supply`
    exceeds four units per day, a `MODERATE` finding contributes."
    PRD §3.4: "otherwise the fill settles in `DUR_REVIEW` awaiting a pharmacist's
    override."

    Design: Corner/calculations/dur_high_dose_moderate_severity
    """
    fx.set_clock()
    drug = fx.create_drug(ndc="77777-0011-01", name="DoseDrug", unit_price_cents=100)
    patient = fx.create_patient(full_name="Dose P", date_of_birth="1980-01-01")
    prescriber = fx.create_prescriber(full_name="Dr Dose", npi="2000000020")
    rx = fx.create_prescription(patient["id"], prescriber["id"], drug["id"],
                                quantity_per_fill=200, days_supply=30)
    fill = fx.create_fill(rx["id"])
    resp = api.run_dur(fill["id"], TECH)
    data = validate_success(resp)
    assert data["dur_severity"] == "MODERATE"
    assert data["status"] == "DUR_REVIEW"


def test_interaction_rule_severe_alert_holds_fill(api):
    """PRD §3.5: "for every interaction rule that pairs the fill's drug with the
    drug on any non-cancelled fill of the same patient, the rule's own
    `severity` contributes."
    PRD §3.4: "otherwise the fill settles in `DUR_REVIEW` awaiting a pharmacist's
    override."

    Design: Corner/calculations/interaction_rule_severe_alert_holds_fill
    """
    fx.set_clock()
    drug_a = fx.create_drug(ndc="77777-0012-01", name="DrugIntA", unit_price_cents=100)
    drug_b = fx.create_drug(ndc="77777-0012-02", name="DrugIntB", unit_price_cents=100)
    fx.create_interaction(drug_a["id"], drug_b["id"], severity="SEVERE", detail="A+B severe")
    patient = fx.create_patient(full_name="Int P", date_of_birth="1980-01-01")
    prescriber = fx.create_prescriber(full_name="Dr Int", npi="2000000021")
    rx_a = fx.create_prescription(patient["id"], prescriber["id"], drug_a["id"],
                                  quantity_per_fill=10, days_supply=30)
    fill_a = fx.create_fill(rx_a["id"])
    validate_success(api.run_dur(fill_a["id"], TECH))
    rx_b = fx.create_prescription(patient["id"], prescriber["id"], drug_b["id"],
                                  quantity_per_fill=10, days_supply=30)
    fill_b = fx.create_fill(rx_b["id"])
    resp = api.run_dur(fill_b["id"], TECH)
    data = validate_success(resp)
    assert data["dur_severity"] == "SEVERE"
    assert data["status"] == "DUR_REVIEW"
    alerts, _ = validate_paginated(api.list_dur_alerts(PHARM, params={"fill_id": fill_b["id"]}))
    assert any(a["severity"] == "SEVERE" and a["alert_type"] == "INTERACTION" for a in alerts), \
        "a SEVERE INTERACTION alert must be recorded for the new fill"


def test_run_dur_from_dispensed_fill_returns_invalid_state(api):
    """PRD §3.4: "This is permitted only when the fill is `ENTERED` (otherwise
    `ERR_FILL_NOT_ENTERED`)".

    Design: Corner/state_machines/run_dur_from_dispensed_fill_returns_invalid_state
    """
    fx.set_clock()
    drug = fx.create_drug(ndc="77777-0001-01", name="DurDrug", unit_price_cents=500)
    patient = fx.create_patient(full_name="Allergic", date_of_birth="1980-01-01",
                                allergy_classes=["PENICILLIN"])
    prescriber = fx.create_prescriber(full_name="Dr DUR", npi="2000000010")
    # Drug name matches allergy class -> SEVERE finding keeps fill in DUR_REVIEW.
    drug2 = fx.create_drug(ndc="77777-0001-02", name="PENICILLIN", unit_price_cents=500)
    rx = fx.create_prescription(patient["id"], prescriber["id"], drug2["id"],
                                quantity_per_fill=10, days_supply=30)
    fill = fx.create_fill(rx["id"])
    validate_success(api.run_dur(fill["id"], TECH))  # now in DUR_REVIEW
    resp = api.run_dur(fill["id"], TECH)
    validate_error(resp, ApiErrorId.ERR_FILL_NOT_ENTERED.value)


def test_cancel_fill_from_already_cancelled_returns_not_cancellable(api):
    """PRD §3.10: "a fill already in a terminal state is rejected with
    `ERR_FILL_NOT_CANCELLABLE`".

    Design: Corner/state_machines/cancel_fill_from_already_cancelled_returns_not_cancellable
    """
    fx.set_clock()
    drug = fx.create_drug(ndc="77777-0008-01", name="Cancel2Drug", unit_price_cents=500)
    patient = fx.create_patient(full_name="Cancel2 P", date_of_birth="1980-01-01")
    prescriber = fx.create_prescriber(full_name="Dr C2", npi="2000000017")
    rx = fx.create_prescription(patient["id"], prescriber["id"], drug["id"],
                                quantity_per_fill=10, days_supply=30)
    fill = fx.create_fill(rx["id"])
    validate_success(api.cancel_fill(fill["id"], TECH))
    resp = api.cancel_fill(fill["id"], PHARM)
    validate_error(resp, ApiErrorId.ERR_FILL_NOT_CANCELLABLE.value)


def test_dispense_from_cancelled_terminal_fill_rejected(api):
    """PRD §3.9: "It requires the fill to be in `WILL_CALL` (otherwise
    `ERR_FILL_NOT_WILL_CALL`)".

    Design: Corner/state_machines/dispense_from_cancelled_terminal_fill_rejected
    """
    fx.set_clock()
    drug = fx.create_drug(ndc="77777-0002-01", name="TermDrug", unit_price_cents=500)
    patient = fx.create_patient(full_name="Term P", date_of_birth="1980-01-01")
    prescriber = fx.create_prescriber(full_name="Dr Term", npi="2000000011")
    rx = fx.create_prescription(patient["id"], prescriber["id"], drug["id"],
                                quantity_per_fill=10, days_supply=30)
    fill = fx.create_fill(rx["id"])
    validate_success(api.cancel_fill(fill["id"], TECH))
    resp = api.dispense(fill["id"], PHARM)
    validate_error(resp, ApiErrorId.ERR_FILL_NOT_WILL_CALL.value)


def test_prescription_expires_via_sweep_past_expiry(api):
    """PRD §3.3: "It becomes `EXPIRED` through an administrator-run sweep that
    checks whether `current_utc` has moved strictly past `expires_utc`; if so,
    the prescription transitions `ACTIVE → EXPIRED`."

    Design: Corner/state_machines/prescription_expires_via_sweep_past_expiry
    """
    fx.set_clock()
    drug = fx.create_drug(ndc="77777-0005-01", name="ExpDrug", unit_price_cents=500)
    patient = fx.create_patient(full_name="Exp P", date_of_birth="1980-01-01")
    prescriber = fx.create_prescriber(full_name="Dr Exp", npi="2000000014")
    rx = fx.create_prescription(patient["id"], prescriber["id"], drug["id"],
                                quantity_per_fill=10, days_supply=30,
                                written_utc="2026-01-01T00:00:00.000Z")
    fx.set_clock("2027-01-02T00:00:00.000Z")
    resp = api.expire_scan_prescription(rx["id"], ADMIN)
    data = validate_success(resp)
    assert data["status"] == "EXPIRED"


def test_will_call_expire_sweep_returns_to_stock_and_reverses(api):
    """PRD §3.10: "the fill transitions to `RETURNED_TO_STOCK`, its
    `claim_status` becomes `REVERSED` as a compensation for the paid claim,
    `plan_paid_cents` is reversed and any payment record is refunded".

    Design: Corner/state_machines/will_call_expire_sweep_returns_to_stock_and_reverses
    """
    fx.set_clock("2026-01-25T00:00:00.000Z")
    plan = fx.create_plan(bin="700003", pcn="CC", name="C Plan C",
                          copay_pct=0.10, copay_max_cents=10000)
    drug = fx.create_drug(ndc="77777-0006-01", name="WcDrug", unit_price_cents=500)
    fx.create_formulary(plan["id"], drug["id"], tier=2, allowed_amount_cents=400)
    patient = fx.create_patient(plan_id=plan["id"], full_name="Wc P",
                                date_of_birth="1980-01-01")
    prescriber = fx.create_prescriber(full_name="Dr Wc", npi="2000000015")
    rx = fx.create_prescription(patient["id"], prescriber["id"], drug["id"],
                                quantity_per_fill=30, days_supply=30,
                                written_utc="2026-01-25T00:00:00.000Z")
    fill = fx.create_fill_will_call(rx["id"])
    fx.set_clock("2026-02-10T00:00:00.000Z")
    resp = api.expire_will_call(fill["id"], ADMIN)
    data = validate_success(resp)
    assert data["status"] == "RETURNED_TO_STOCK"
    assert data["claim_status"] == "REVERSED"
    assert data["plan_paid_cents"] == 0


def test_approve_already_approved_pa_returns_pa_not_pending(api):
    """PRD §3.10: "Approval requires the request to be `PENDING` (otherwise
    `ERR_PA_NOT_PENDING`)".

    Design: Corner/state_machines/approve_already_approved_pa_returns_pa_not_pending
    """
    s = fx.setup_pa_referral(drug_overrides={"ndc": "77777-0003-01", "name": "PaDrug",
                                             "unit_price_cents": 500, "pa_required": True},
                             plan_overrides={"bin": "700002", "pcn": "CB", "name": "C Plan B",
                                             "copay_pct": 0.10, "copay_max_cents": 10000},
                             prescriber_overrides={"full_name": "Dr Pa", "npi": "2000000012"},
                             qty=10)
    pa = s["pa"]
    fx.approve_pa(pa["id"], pa["version"])
    pa2 = validate_success(api.get_prior_auth_request(pa["id"], PHARM))
    resp = api.approve_prior_auth(pa["id"],
                                  {"expected_priorauthrequest_version": pa2["version"]},
                                  PHARM)
    validate_error(resp, ApiErrorId.ERR_PA_NOT_PENDING.value)
