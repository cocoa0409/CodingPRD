"""Business-safety, temporal, and constraint validations; refill-too-soon and
will-call temporal windows.

Translations of queue B `validations` and `errors` instances, plus queue A
resource_temporal_overlap and the refill-too-soon boundary_precision instances.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    submit_claim_payload, create_payment_record_payload, create_prescription_payload,
)
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["admin_headers"]
TECH = TEST_USERS["technician_headers"]
PHARM = TEST_USERS["pharmacist_headers"]
CASH = TEST_USERS["cashier_headers"]


# ---------------------------------------------------------------------------
# Queue B — validations
# ---------------------------------------------------------------------------
def test_controlled_prescription_requires_active_dea(api):
    """PRD §3.3: "If the prescribed drug is controlled, intake additionally
    requires the prescriber to have a `dea_number` on file with `dea_active`
    true; otherwise the intake is rejected with `ERR_PRESCRIBER_DEA_INVALID`
    (HTTP 422)."

    Design: Corner/validations/controlled_prescription_requires_active_dea
    """
    fx.set_clock()
    drug = fx.create_drug(ndc="77777-0013-01", name="DeaDrug", dea_schedule="CII",
                          unit_price_cents=1000)
    patient = fx.create_patient(full_name="Dea P", date_of_birth="1980-01-01")
    prescriber = fx.create_prescriber(full_name="Dr NoDea", npi="2000000022", dea_active=False)
    resp = api.create_prescription(
        create_prescription_payload(patient["id"], prescriber["id"], drug["id"],
                                    quantity_per_fill=10, days_supply=30),
        TECH,
    )
    validate_error(resp, ApiErrorId.ERR_PRESCRIBER_DEA_INVALID.value)


def test_submit_claim_drug_not_on_formulary(api):
    """PRD §3.6: "for an insured patient, the drug must appear on the patient's
    plan formulary (or be flagged for prior auth); a drug absent from the
    formulary is rejected with `ERR_DRUG_NOT_ON_FORMULARY` (HTTP 422)."

    Design: Corner/validations/submit_claim_drug_not_on_formulary
    """
    fx.set_clock()
    plan = fx.create_plan(bin="700005", pcn="CE", name="NoForm Plan",
                          copay_pct=0.10, copay_max_cents=10000)
    drug = fx.create_drug(ndc="77777-0014-01", name="OffFormDrug", unit_price_cents=500)
    patient = fx.create_patient(plan_id=plan["id"], full_name="NoForm P",
                                date_of_birth="1980-01-01")
    prescriber = fx.create_prescriber(full_name="Dr NoForm", npi="2000000023")
    rx = fx.create_prescription(patient["id"], prescriber["id"], drug["id"],
                                quantity_per_fill=10, days_supply=30)
    fill = fx.create_fill_at_adjudicating(rx["id"])
    v = fx.get_rx_version(rx["id"])
    resp = api.submit_claim(fill["id"], submit_claim_payload(v), TECH)
    validate_error(resp, ApiErrorId.ERR_DRUG_NOT_ON_FORMULARY.value)


def test_submit_claim_blocked_by_unoverridden_dur(api):
    """PRD §3.4: "This is permitted only when the fill is `ENTERED`...The fill
    must be in `ADJUDICATING` (otherwise `ERR_FILL_NOT_ADJUDICATING`)".
    PRD §3.6: "The fill must be in `ADJUDICATING` (otherwise
    `ERR_FILL_NOT_ADJUDICATING`)".

    Design: Corner/validations/submit_claim_blocked_by_unoverridden_dur
    """
    fx.set_clock()
    # MODERATE high-dose finding keeps the fill in DUR_REVIEW (never ADJUDICATING).
    s = fx.setup_fill_in_dur_review_high_dose(qty=200, days_supply=30)
    fill = s["fill"]
    assert fill["status"] == "DUR_REVIEW"
    v = fx.get_rx_version(s["rx"]["id"])
    resp = api.submit_claim(fill["id"], submit_claim_payload(v), TECH)
    validate_error(resp, ApiErrorId.ERR_FILL_NOT_ADJUDICATING.value)


def test_override_severe_dur_without_reason_rejected(api):
    """PRD §3.4: "every `MODERATE` and `SEVERE` alert on the fill must carry an
    `override_reason` — an `override_reason` is therefore mandatory whenever a
    `SEVERE` alert is present, and its absence is rejected with
    `ERR_OVERRIDE_REASON_REQUIRED` (HTTP 422)."

    Design: Corner/validations/override_severe_dur_without_reason_rejected
    """
    s = fx.setup_fill_in_dur_review_severe_allergy(allergy="PENICILLIN")
    fill = s["fill"]
    assert fill["dur_severity"] == "SEVERE"
    resp = api.override_dur(fill["id"], {}, PHARM)
    validate_error(resp, ApiErrorId.ERR_OVERRIDE_REASON_REQUIRED.value)


def test_no_refills_remaining_on_extra_fill(api):
    """PRD §3.4: "Creating a refill — any fill whose `fill_sequence` is greater
    than 1 — requires `refills_remaining` to be greater than 0 at creation time,
    otherwise the creation is rejected with `ERR_NO_REFILLS_REMAINING`."

    Design: Corner/validations/no_refills_remaining_on_extra_fill

    refills_remaining must reach 0 while the prescription is still `ACTIVE`, so
    that the §3.4 business check fires rather than the higher-priority
    `ERR_PRESCRIPTION_NOT_ACTIVE` state gate. Per PRD §3.3 a fill consumes a
    refill while ADJUDICATING/PA_REFERRAL/READY_FILL/WILL_CALL/DISPENSED and the
    prescription only auto-EXHAUSTS "on the back of a dispense"; so we drive a
    single refill (fill_sequence 2) into ADJUDICATING (consuming, not dispensed)
    against a one-refill prescription, which floors refills_remaining at 0 with
    the prescription still ACTIVE. The next refill (fill_sequence 3) must then be
    rejected with `ERR_NO_REFILLS_REMAINING`.
    """
    fx.set_clock()
    plan = fx.create_plan(bin="700007", pcn="CG", name="NoRefill Plan",
                          copay_pct=0.10, copay_max_cents=10000)
    drug = fx.create_drug(ndc="77777-0017-01", name="NoRefillDrug", unit_price_cents=500)
    fx.create_formulary(plan["id"], drug["id"], tier=2, allowed_amount_cents=400)
    patient = fx.create_patient(plan_id=plan["id"], full_name="NoRefill P",
                                date_of_birth="1980-01-01")
    prescriber = fx.create_prescriber(full_name="Dr NoRefill", npi="2000000026")
    rx = fx.create_prescription(patient["id"], prescriber["id"], drug["id"],
                                quantity_per_fill=30, days_supply=30,
                                refills_authorized=1)
    fx.create_fill(rx["id"])  # original fill (fill_sequence 1) — never consumes
    # Refill (fill_sequence 2) into ADJUDICATING -> consumes the lone refill.
    # The prescription stays ACTIVE because no dispense has occurred (auto-EXHAUST
    # only fires "on the back of a dispense"), so the §3.4 business check — not the
    # `ERR_PRESCRIPTION_NOT_ACTIVE` state gate — is what must reject the next refill.
    fx.create_fill_at_adjudicating(rx["id"])
    rx_now = validate_success(api.get_prescription(rx["id"], TECH))
    assert rx_now["status"] == "ACTIVE"
    # Creating the next refill (fill_sequence 3) recomputes refills_remaining
    # (creation is a §3.3 reconciliation point); with fill_sequence 2 consuming,
    # refills_remaining floors at 0 and the creation is rejected.
    resp = api.create_fill({"prescription_id": rx["id"]}, TECH)
    validate_error(resp, ApiErrorId.ERR_NO_REFILLS_REMAINING.value)


def test_payment_amount_mismatch_rejected(api):
    """PRD §3.9: "For an insured fill the `amount_cents` must equal the fill's
    `final_copay_cents`; for a cash patient it must equal the fill's
    `gross_amount_cents`; a mismatch is rejected with
    `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 422)."

    Design: Corner/validations/payment_amount_mismatch_rejected
    """
    fx.set_clock()
    plan = fx.create_plan(bin="700008", pcn="CH", name="Pay Plan", copay_pct=0.20,
                          copay_min_cents=500, copay_max_cents=10000, dispensing_fee_cents=100)
    drug = fx.create_drug(ndc="77777-0018-01", name="PayDrug", unit_price_cents=800)
    fx.create_formulary(plan["id"], drug["id"], tier=2, allowed_amount_cents=600)
    patient = fx.create_patient(plan_id=plan["id"], full_name="Pay P",
                                date_of_birth="1980-01-01")
    prescriber = fx.create_prescriber(full_name="Dr Pay", npi="2000000027")
    rx = fx.create_prescription(patient["id"], prescriber["id"], drug["id"],
                                quantity_per_fill=30, days_supply=30)
    fill = fx.create_fill_paid(rx["id"])  # final_copay 3620
    resp = api.create_payment_record(
        create_payment_record_payload(fill["id"], 1000), CASH
    )
    validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH.value)


def test_dispense_without_payment_rejected(api):
    """PRD §3.9: "a payment record to exist for the fill whose `amount_cents`
    equals the fill's `final_copay_cents`, otherwise `ERR_PAYMENT_REQUIRED`."

    Design: Corner/validations/dispense_without_payment_rejected
    """
    fx.set_clock()
    plan = fx.create_plan(bin="700009", pcn="CI", name="NoPay Plan",
                          copay_pct=0.10, copay_max_cents=10000)
    drug = fx.create_drug(ndc="77777-0019-01", name="NoPayDrug", unit_price_cents=500)
    fx.create_formulary(plan["id"], drug["id"], tier=2, allowed_amount_cents=400)
    patient = fx.create_patient(plan_id=plan["id"], full_name="NoPay P",
                                date_of_birth="1980-01-01")
    prescriber = fx.create_prescriber(full_name="Dr NoPay", npi="2000000028")
    rx = fx.create_prescription(patient["id"], prescriber["id"], drug["id"],
                                quantity_per_fill=30, days_supply=30)
    fill = fx.create_fill_will_call(rx["id"])  # WILL_CALL, no payment
    resp = api.dispense(fill["id"], PHARM)
    validate_error(resp, ApiErrorId.ERR_PAYMENT_REQUIRED.value)


def test_discontinue_blocked_by_open_fill(api):
    """PRD §3.3: "requires that no fill of the prescription sit in a non-terminal
    workflow state other than `ENTERED` (otherwise `ERR_OPEN_FILL_EXISTS`)."

    Design: Corner/validations/discontinue_blocked_by_open_fill
    """
    fx.set_clock()
    plan = fx.create_plan(bin="700010", pcn="CJ", name="Open Plan",
                          copay_pct=0.10, copay_max_cents=10000)
    drug = fx.create_drug(ndc="77777-0020-01", name="OpenDrug", unit_price_cents=500)
    fx.create_formulary(plan["id"], drug["id"], tier=2, allowed_amount_cents=400)
    patient = fx.create_patient(plan_id=plan["id"], full_name="Open P",
                                date_of_birth="1980-01-01")
    prescriber = fx.create_prescriber(full_name="Dr Open", npi="2000000029")
    rx = fx.create_prescription(patient["id"], prescriber["id"], drug["id"],
                                quantity_per_fill=30, days_supply=30)
    fx.create_fill_paid(rx["id"])  # fill in READY_FILL (non-ENTERED, non-terminal)
    resp = api.discontinue_prescription(rx["id"], PHARM)
    validate_error(resp, ApiErrorId.ERR_OPEN_FILL_EXISTS.value)


def test_missing_user_context_rejected(api):
    """PRD §2.1: "If either header is absent or malformed, the request is
    rejected with `ERR_MISSING_USER_CONTEXT` (HTTP 401)."

    Design: Corner/validations/missing_user_context_rejected
    """
    fx.set_clock()
    resp = api.create_drug_product(
        {"ndc": "77777-0021-01", "name": "NoAuthDrug", "unit_price_cents": 100}, {}
    )
    validate_error(resp, ApiErrorId.ERR_MISSING_USER_CONTEXT.value)


# ---------------------------------------------------------------------------
# Queue B — endpoints / errors
# ---------------------------------------------------------------------------
def test_reverse_claim_after_dispense_rejected(api):
    """PRD §3.9: "Reversal requires the `claim_status` to be `PAID` (otherwise
    `ERR_CLAIM_NOT_PAID`) and the fill not to be `DISPENSED` (otherwise
    `ERR_FILL_ALREADY_DISPENSED`)".

    Design: Corner/endpoints/reverse_claim_after_dispense_rejected
    """
    fx.set_clock()
    plan = fx.create_plan(bin="700011", pcn="CK", name="Rev Plan",
                          copay_pct=0.10, copay_max_cents=10000)
    drug = fx.create_drug(ndc="77777-0022-01", name="RevDrug", unit_price_cents=500)
    fx.create_formulary(plan["id"], drug["id"], tier=2, allowed_amount_cents=400)
    patient = fx.create_patient(plan_id=plan["id"], full_name="Rev P",
                                date_of_birth="1980-01-01")
    prescriber = fx.create_prescriber(full_name="Dr Rev", npi="2000000030")
    rx = fx.create_prescription(patient["id"], prescriber["id"], drug["id"],
                                quantity_per_fill=30, days_supply=30)
    fx.create_and_dispense_fill(rx["id"], 1210)
    # Fetch the dispensed fill id.
    fill_list, _ = validate_paginated(api.list_fills(PHARM, params={"prescription_id": rx["id"]}))
    dispensed = fill_list[0]
    resp = api.reverse_claim(dispensed["id"], PHARM)
    validate_error(resp, ApiErrorId.ERR_FILL_ALREADY_DISPENSED.value)


def test_drug_discontinued_blocks_prescription(api):
    """PRD §3.3: "Intake against a drug whose `status` is `DISCONTINUED` is
    rejected with `ERR_DRUG_DISCONTINUED`."

    Design: Corner/errors/drug_discontinued_blocks_prescription
    """
    fx.set_clock()
    drug = fx.create_drug(ndc="77777-0027-01", name="DiscDrug", unit_price_cents=500)
    validate_success(api.discontinue_drug_product(drug["id"], ADMIN))
    patient = fx.create_patient(full_name="Disc P", date_of_birth="1980-01-01")
    prescriber = fx.create_prescriber(full_name="Dr Disc", npi="2000000035")
    resp = api.create_prescription(
        create_prescription_payload(patient["id"], prescriber["id"], drug["id"],
                                    quantity_per_fill=10, days_supply=30),
        TECH,
    )
    validate_error(resp, ApiErrorId.ERR_DRUG_DISCONTINUED.value)


# ---------------------------------------------------------------------------
# Queue A — refill-too-soon boundary and overlap
# ---------------------------------------------------------------------------
def _setup_first_dispense_then_refill(bin_, pcn_, ndc_, refill_clock):
    """First fill DISPENSED on 2026-01-01 (days_supply 30, threshold 0.80 ->
    required 24 days). Clock advanced to refill_clock, second fill created and
    run-dur'd to ADJUDICATING. Returns (rx_id, f2_id)."""
    fx.set_clock("2026-01-01T00:00:00.000Z")
    plan = fx.create_plan(bin=bin_, pcn=pcn_, name="RTS Plan", copay_pct=0.10,
                          copay_max_cents=10000, refill_too_soon_threshold_pct=0.80)
    drug = fx.create_drug(ndc=ndc_, name="RtsDrug", unit_price_cents=500)
    fx.create_formulary(plan["id"], drug["id"], tier=2, allowed_amount_cents=400)
    patient = fx.create_patient(plan_id=plan["id"], full_name="RTS P",
                                date_of_birth="1990-01-01")
    prescriber = fx.create_prescriber(full_name="Dr RTS", npi=f"100000{ndc_[-5:-3]}40")
    rx = fx.create_prescription(patient["id"], prescriber["id"], drug["id"],
                                quantity_per_fill=30, days_supply=30,
                                refills_authorized=3, written_utc="2026-01-01T00:00:00.000Z")
    fx.create_and_dispense_fill(rx["id"], 1210)
    fx.set_clock(refill_clock)
    f2 = fx.create_fill_at_adjudicating(rx["id"])
    return rx["id"], f2["id"]


def test_refill_too_soon_exact_boundary_elapsed_equals_required(api):
    """PRD §3.8: "The refill is allowed only when the elapsed days are greater
    than or equal to the required days; when elapsed days equal required days the
    refill passes, and when elapsed days fall one short the refill is rejected
    with `ERR_REFILL_TOO_SOON`."

    Design: Difficulty/boundary_precision_check/refill_too_soon_exact_boundary_elapsed_equals_required
    """
    rx_id, f2_id = _setup_first_dispense_then_refill("611101", "K1", "00000-1101-01",
                                                     "2026-01-25T00:00:00.000Z")  # 24 days
    v = fx.get_rx_version(rx_id)
    data = validate_success(api.submit_claim(f2_id, submit_claim_payload(v), TECH))
    assert data["status"] == "READY_FILL"
    assert data["claim_status"] == "PAID"


def test_refill_too_soon_one_day_short_rejected(api):
    """PRD §3.8: "when elapsed days fall one short the refill is rejected with
    `ERR_REFILL_TOO_SOON`."

    Design: Difficulty/boundary_precision_check/refill_too_soon_exact_boundary_elapsed_equals_required
    """
    rx_id, f2_id = _setup_first_dispense_then_refill("611102", "K2", "00000-1102-01",
                                                     "2026-01-24T00:00:00.000Z")  # 23 days
    v = fx.get_rx_version(rx_id)
    resp = api.submit_claim(f2_id, submit_claim_payload(v), TECH)
    validate_error(resp, ApiErrorId.ERR_REFILL_TOO_SOON.value)


def test_refill_too_soon_overlap_prior_supply_window(api):
    """PRD §3.8: "It then computes the elapsed days as the whole number of
    calendar days between the parent prescription's `last_dispensed_utc` and
    `current_utc`, also floored. The refill is allowed only when the elapsed days
    are greater than or equal to the required days".

    Design: Difficulty/resource_temporal_overlap/refill_too_soon_overlap_prior_supply_window
    """
    rx_id, f2_id = _setup_first_dispense_then_refill("611103", "K3", "00000-1103-01",
                                                     "2026-01-24T00:00:00.000Z")  # 23 days < 24
    v = fx.get_rx_version(rx_id)
    resp = api.submit_claim(f2_id, submit_claim_payload(v), TECH)
    validate_error(resp, ApiErrorId.ERR_REFILL_TOO_SOON.value)


def test_refill_too_soon_overlap_rejects_inside_protected_window(api):
    """PRD §3.8: "During claim submission the system computes the required elapsed
    days as the prior fill's `days_supply` multiplied by the plan's
    `refill_too_soon_threshold_pct` (which defaults to 0.80), with the product
    floored to a whole number of days."

    Design: Difficulty/resource_temporal_overlap/refill_too_soon_overlap_prior_supply_window
    """
    # required_days = floor(30 * 0.80) = 24; a refill at 10 elapsed days sits deep
    # inside the still-active prior-supply window and must be rejected.
    rx_id, f2_id = _setup_first_dispense_then_refill("611104", "K4", "00000-1104-01",
                                                     "2026-01-11T00:00:00.000Z")  # 10 days
    v = fx.get_rx_version(rx_id)
    resp = api.submit_claim(f2_id, submit_claim_payload(v), TECH)
    validate_error(resp, ApiErrorId.ERR_REFILL_TOO_SOON.value)


def test_will_call_pickup_deadline_window_expiry_overlap(api):
    """PRD §3.9: "the will-call window to be open — `current_utc` at or before
    `pickup_deadline_utc`, otherwise `ERR_WILL_CALL_EXPIRED`".

    Design: Difficulty/resource_temporal_overlap/will_call_pickup_deadline_window_expiry_overlap
    """
    fx.set_clock("2026-01-25T00:00:00.000Z")
    plan = fx.create_plan(bin="610015", pcn="PO", name="Plan O",
                          copay_pct=0.10, copay_max_cents=10000)
    drug = fx.create_drug(ndc="00000-0015-01", name="November", unit_price_cents=500)
    fx.create_formulary(plan["id"], drug["id"], tier=2, allowed_amount_cents=400)
    patient = fx.create_patient(plan_id=plan["id"], full_name="Pat Sixteen",
                                date_of_birth="1993-03-03")
    prescriber = fx.create_prescriber(full_name="Dr O", npi="1000000150")
    rx = fx.create_prescription(patient["id"], prescriber["id"], drug["id"],
                                quantity_per_fill=30, days_supply=30,
                                written_utc="2026-01-25T00:00:00.000Z")
    fill = fx.create_fill_will_call(rx["id"])  # staged 2026-01-25, deadline 2026-02-04
    fx.pay_for_fill(fill["id"], 1210)
    fx.set_clock("2026-02-05T00:00:00.000Z")  # past deadline
    resp = api.dispense(fill["id"], PHARM)
    validate_error(resp, ApiErrorId.ERR_WILL_CALL_EXPIRED.value)


def test_will_call_dispense_inside_window_succeeds(api):
    """PRD §3.9: "on success the fill moves to `WILL_CALL` and its
    `pickup_deadline_utc` is set to 10 days after `current_utc`."
    PRD §3.9: "the will-call window to be open — `current_utc` at or before
    `pickup_deadline_utc`".

    Design: Difficulty/resource_temporal_overlap/will_call_pickup_deadline_window_expiry_overlap
    """
    # The complementary in-window case: at exactly the deadline (10 days after
    # staging) the window is still open ("at or before") and dispense succeeds.
    fx.set_clock("2026-01-25T00:00:00.000Z")
    plan = fx.create_plan(bin="611015", pcn="PO2", name="Plan O2",
                          copay_pct=0.10, copay_max_cents=10000)
    drug = fx.create_drug(ndc="00000-1015-01", name="November2", unit_price_cents=500)
    fx.create_formulary(plan["id"], drug["id"], tier=2, allowed_amount_cents=400)
    patient = fx.create_patient(plan_id=plan["id"], full_name="Pat O2",
                                date_of_birth="1993-03-03")
    prescriber = fx.create_prescriber(full_name="Dr O2", npi="1000001150")
    rx = fx.create_prescription(patient["id"], prescriber["id"], drug["id"],
                                quantity_per_fill=30, days_supply=30,
                                written_utc="2026-01-25T00:00:00.000Z")
    fill = fx.create_fill_will_call(rx["id"])  # staged 2026-01-25, deadline 2026-02-04
    fx.pay_for_fill(fill["id"], 1210)
    fx.set_clock("2026-02-04T00:00:00.000Z")  # exactly the deadline -> still open
    data = validate_success(api.dispense(fill["id"], PHARM))
    assert data["status"] == "DISPENSED"
