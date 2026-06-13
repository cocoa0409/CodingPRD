"""Prior-auth referral cycle, PA decisions, expiry, OCC, compensating invariants.

Translations of queue A non_linear_state_machine (fill cycle), compensating_invariant
(money + refills), cross_entity_state_dependency, transitive_cascade (discontinue),
and queue B errors (PA expired, stale PA version, stale prescription version, OCC
increment).
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    submit_claim_payload, approve_pa_payload,
)
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["admin_headers"]
TECH = TEST_USERS["technician_headers"]
PHARM = TEST_USERS["pharmacist_headers"]
CASH = TEST_USERS["cashier_headers"]


# ---------------------------------------------------------------------------
# Queue A — cyclic fill: ADJUDICATING -> PA_REFERRAL -> ADJUDICATING
# ---------------------------------------------------------------------------
def test_fill_cycle_adjudicating_pa_referral_adjudicating(api):
    """PRD §3.10: "On approval the request transitions from `PENDING` to
    `APPROVED`, sets `decided_utc` to `current_utc`, increments its own
    `version` by one, and cycles the linked fill back: the fill's `claim_status`
    returns to `UNCLAIMED` and its `status` returns from `PA_REFERRAL` to
    `ADJUDICATING`".

    Design: Difficulty/non_linear_state_machine/fill_cycle_adjudicating_pa_referral_adjudicating
    """
    s = fx.setup_pa_referral(
        plan_overrides={"bin": "610005", "pcn": "PE", "name": "Plan E",
                        "copay_pct": 0.10, "copay_max_cents": 10000},
        drug_overrides={"ndc": "00000-0005-01", "name": "Delta PA",
                        "unit_price_cents": 500, "pa_required": True},
        prescriber_overrides={"full_name": "Dr E", "npi": "1000000005"},
    )
    pa = s["pa"]
    approved = fx.approve_pa(pa["id"], pa["version"])
    assert approved["status"] == "APPROVED"
    fill = validate_success(api.get_fill(s["fill"]["id"], PHARM))
    assert fill["status"] == "ADJUDICATING"
    assert fill["claim_status"] == "UNCLAIMED"


def test_fill_cycle_resubmit_after_pa_approval_clears_to_ready(api):
    """PRD §3.10: "so the claim can be resubmitted and — because an approved
    request now exists — clear to `READY_FILL`."
    PRD §3.6: "An already-`APPROVED` prior-auth request for the fill suppresses
    re-referral so that the resubmitted claim clears straight through."

    Design: Difficulty/non_linear_state_machine/fill_cycle_adjudicating_pa_referral_adjudicating
    """
    s = fx.setup_pa_referral(
        plan_overrides={"bin": "610025", "pcn": "PE2", "name": "Plan E2",
                        "copay_pct": 0.10, "copay_max_cents": 10000},
        drug_overrides={"ndc": "00000-0025-01", "name": "Delta2 PA",
                        "unit_price_cents": 500, "pa_required": True},
        prescriber_overrides={"full_name": "Dr E2", "npi": "1000000025"},
    )
    pa = s["pa"]
    fx.approve_pa(pa["id"], pa["version"])  # cycles fill back to ADJUDICATING
    # Resubmit the claim: the now-APPROVED PA suppresses re-referral -> READY_FILL.
    data = fx.submit_claim(s["fill"]["id"], s["rx"]["id"])
    assert data["status"] == "READY_FILL"
    assert data["claim_status"] == "PAID"


# ---------------------------------------------------------------------------
# Queue A — cross-entity: controlled fill blocked by LOCKED patient
# ---------------------------------------------------------------------------
def test_fill_submit_blocked_by_patient_controlled_locked(api):
    """PRD §3.6: "For a controlled drug, the patient's `controlled_status` must be
    `ELIGIBLE`, otherwise `ERR_PATIENT_CONTROLLED_LOCKED` (HTTP 403)."

    Design: Difficulty/cross_entity_state_dependency/fill_submit_blocked_by_patient_controlled_locked
    """
    s = fx.setup_controlled_patient_with_dispenses(
        n_prescribers=3, n_dispenses=3, clock="2026-03-01T00:00:00.000Z",
        drug_overrides={"ndc": "00000-0012-01", "name": "Kilo CII",
                        "dea_schedule": "CII", "unit_price_cents": 1000},
        plan_overrides={"bin": "610012", "pcn": "PL", "name": "Plan L",
                        "copay_pct": 0.10, "copay_max_cents": 10000},
    )
    patient = validate_success(api.get_patient(s["patient"]["id"], PHARM))
    assert patient["controlled_status"] == "LOCKED", "precondition: patient must be LOCKED"
    # Fresh controlled prescription + fill, take to ADJUDICATING, then submit.
    rx = fx.create_prescription(s["patient"]["id"], s["prescribers"][0]["id"], s["drug"]["id"],
                                quantity_per_fill=10, days_supply=30,
                                written_utc="2026-03-01T00:00:00.000Z")
    fill = fx.create_fill_at_adjudicating(rx["id"])
    v = fx.get_rx_version(rx["id"])
    resp = api.submit_claim(fill["id"], submit_claim_payload(v), TECH)
    validate_error(resp, ApiErrorId.ERR_PATIENT_CONTROLLED_LOCKED.value)


def test_locked_patient_status_403_on_controlled_submit(api):
    """PRD §3.2: "at that point the parallel `controlled_status` flips to
    `LOCKED`, after which new controlled claims are refused."
    PRD §3.6: "For a controlled drug, the patient's `controlled_status` must be
    `ELIGIBLE`, otherwise `ERR_PATIENT_CONTROLLED_LOCKED` (HTTP 403)."

    Design: Difficulty/cross_entity_state_dependency/fill_submit_blocked_by_patient_controlled_locked
    """
    s = fx.setup_controlled_patient_with_dispenses(
        n_prescribers=3, n_dispenses=3, clock="2026-03-01T00:00:00.000Z",
        drug_overrides={"ndc": "00000-0026-01", "name": "Kilo2 CII",
                        "dea_schedule": "CII", "unit_price_cents": 1000},
        plan_overrides={"bin": "610026", "pcn": "PL2", "name": "Plan L2",
                        "copay_pct": 0.10, "copay_max_cents": 10000},
    )
    rx = fx.create_prescription(s["patient"]["id"], s["prescribers"][1]["id"], s["drug"]["id"],
                                quantity_per_fill=10, days_supply=30,
                                written_utc="2026-03-01T00:00:00.000Z")
    fill = fx.create_fill_at_adjudicating(rx["id"])
    v = fx.get_rx_version(rx["id"])
    resp = api.submit_claim(fill["id"], submit_claim_payload(v), TECH)
    err = validate_error(resp, ApiErrorId.ERR_PATIENT_CONTROLLED_LOCKED.value)
    assert err["error_id"] == "ERR_PATIENT_CONTROLLED_LOCKED"


# ---------------------------------------------------------------------------
# Queue A — cross-entity: run-dur blocked by discontinued parent prescription
# ---------------------------------------------------------------------------
def test_fill_create_blocked_by_prescription_not_active(api):
    """PRD §3.4: "A fill cannot be created against a prescription that is not
    `ACTIVE` (`ERR_PRESCRIPTION_NOT_ACTIVE`)".

    Design: Difficulty/cross_entity_state_dependency/fill_create_blocked_by_prescription_not_active

    The blocking state lives on the parent Prescription: once it is DISCONTINUED
    (a non-ACTIVE state), the create-fill endpoint must reject the new fill at
    creation time. (Discontinue cascades every still-ENTERED fill to CANCELLED,
    so a fresh ENTERED fill cannot survive under the discontinued parent to be
    surfaced via run-dur — the create gate is the faithful surface for the
    DISCONTINUED route; the EXPIRED route exercises the run-dur gate in the
    companion test.)
    """
    fx.set_clock()
    plan = fx.create_plan(bin="610013", pcn="PM", name="Plan M",
                          copay_pct=0.10, copay_max_cents=10000)
    drug = fx.create_drug(ndc="00000-0013-01", name="Lima", unit_price_cents=500)
    patient = fx.create_patient(plan_id=plan["id"], full_name="Pat Fourteen",
                                date_of_birth="1999-09-09")
    prescriber = fx.create_prescriber(full_name="Dr M", npi="1000000130")
    rx = fx.create_prescription(patient["id"], prescriber["id"], drug["id"],
                                quantity_per_fill=30, days_supply=30,
                                refills_authorized=1)
    # Get first fill out of ENTERED then cancel, so discontinue is allowed.
    f1 = fx.create_fill(rx["id"])
    validate_success(api.run_dur(f1["id"], TECH))
    validate_success(api.cancel_fill(f1["id"], PHARM))
    validate_success(api.discontinue_prescription(rx["id"], PHARM))
    # Creating a fill against the now-DISCONTINUED prescription must be rejected.
    resp = api.create_fill({"prescription_id": rx["id"]}, TECH)
    validate_error(resp, ApiErrorId.ERR_PRESCRIPTION_NOT_ACTIVE.value)


def test_fill_create_against_expired_prescription_blocked_at_dur(api):
    """PRD §3.4: "the parent prescription is `ACTIVE` (otherwise
    `ERR_PRESCRIPTION_NOT_ACTIVE`)".
    PRD §3.3: "It becomes `EXPIRED` through an administrator-run sweep that checks
    whether `current_utc` has moved strictly past `expires_utc`; if so, the
    prescription transitions `ACTIVE → EXPIRED`."

    Design: Difficulty/cross_entity_state_dependency/fill_create_blocked_by_prescription_not_active
    """
    # A different route to a non-ACTIVE parent (EXPIRED rather than DISCONTINUED):
    # the blocking state still lives on the Prescription, surfaced via run-dur.
    fx.set_clock("2026-01-01T00:00:00.000Z")
    plan = fx.create_plan(bin="610027", pcn="PM2", name="Plan M2",
                          copay_pct=0.10, copay_max_cents=10000)
    drug = fx.create_drug(ndc="00000-0027-01", name="Lima2", unit_price_cents=500)
    patient = fx.create_patient(plan_id=plan["id"], full_name="Pat M2",
                                date_of_birth="1999-09-09")
    prescriber = fx.create_prescriber(full_name="Dr M2", npi="1000000230")
    rx = fx.create_prescription(patient["id"], prescriber["id"], drug["id"],
                                quantity_per_fill=30, days_supply=30,
                                written_utc="2026-01-01T00:00:00.000Z")
    fill = fx.create_fill(rx["id"])  # ENTERED while still ACTIVE
    fx.set_clock("2027-01-02T00:00:00.000Z")  # past 365-day expiry
    validate_success(api.expire_scan_prescription(rx["id"], ADMIN))
    resp = api.run_dur(fill["id"], TECH)
    validate_error(resp, ApiErrorId.ERR_PRESCRIPTION_NOT_ACTIVE.value)


# ---------------------------------------------------------------------------
# Queue A — compensating invariant: reverse-claim conserves money
# ---------------------------------------------------------------------------
def test_reverse_claim_conserves_fill_money_ledger(api):
    """PRD §3.9: "it sets `claim_status` to `REVERSED`, reverses `plan_paid_cents`
    back to 0, and refunds any existing payment record by setting its `refunded`
    flag to true. Reversal conserves money: `gross_amount_cents` is untouched
    while the plan-paid and final copay amounts revert to 0."

    Design: Difficulty/compensating_invariant/reverse_claim_conserves_fill_money_ledger
    """
    fx.set_clock()
    plan = fx.create_plan(bin="610016", pcn="PP", name="Plan P", copay_pct=0.20,
                          copay_min_cents=500, copay_max_cents=10000, dispensing_fee_cents=100)
    drug = fx.create_drug(ndc="00000-0016-01", name="Oscar", unit_price_cents=800)
    fx.create_formulary(plan["id"], drug["id"], tier=2, allowed_amount_cents=600)
    patient = fx.create_patient(plan_id=plan["id"], full_name="Pat Seventeen",
                                date_of_birth="1994-04-04")
    prescriber = fx.create_prescriber(full_name="Dr P", npi="1000000160")
    rx = fx.create_prescription(patient["id"], prescriber["id"], drug["id"],
                                quantity_per_fill=30, days_supply=30)
    fill = fx.create_fill_paid(rx["id"])  # PAID, plan_paid 14480, final 3620
    payment = fx.pay_for_fill(fill["id"], 3620)
    reversed_fill = validate_success(api.reverse_claim(fill["id"], PHARM))
    assert reversed_fill["claim_status"] == "REVERSED"
    assert reversed_fill["plan_paid_cents"] == 0
    assert reversed_fill["gross_amount_cents"] == 24000  # 800*30 untouched
    refreshed_payment = validate_success(api.get_payment_record(payment["id"], PHARM))
    assert refreshed_payment["refunded"] is True


def test_reverse_claim_refunds_payment_and_zeroes_plan_paid(api):
    """PRD §3.9: "it sets `claim_status` to `REVERSED`, reverses `plan_paid_cents`
    back to 0, and refunds any existing payment record by setting its `refunded`
    flag to true."

    Design: Difficulty/compensating_invariant/reverse_claim_conserves_fill_money_ledger
    """
    fx.set_clock()
    plan = fx.create_plan(bin="610036", pcn="PP2", name="Plan P2", copay_pct=0.20,
                          copay_min_cents=500, copay_max_cents=10000, dispensing_fee_cents=100)
    drug = fx.create_drug(ndc="00000-0036-01", name="Oscar2", unit_price_cents=800)
    fx.create_formulary(plan["id"], drug["id"], tier=2, allowed_amount_cents=600)
    patient = fx.create_patient(plan_id=plan["id"], full_name="Pat P2",
                                date_of_birth="1994-04-04")
    prescriber = fx.create_prescriber(full_name="Dr P2", npi="1000000360")
    rx = fx.create_prescription(patient["id"], prescriber["id"], drug["id"],
                                quantity_per_fill=30, days_supply=30)
    fill = fx.create_fill_paid(rx["id"])
    payment = fx.pay_for_fill(fill["id"], 3620)
    reversed_fill = validate_success(api.reverse_claim(fill["id"], PHARM))
    assert reversed_fill["plan_paid_cents"] == 0
    refreshed_payment = validate_success(api.get_payment_record(payment["id"], PHARM))
    assert refreshed_payment["refunded"] is True


# ---------------------------------------------------------------------------
# Queue A — compensating invariant: PA deny conserves refills_remaining
# ---------------------------------------------------------------------------
def test_pa_deny_conserves_refills_remaining_count(api):
    """PRD §3.10: "it transitions the request from `PENDING` to `DENIED`, sets
    `decided_utc` to `current_utc`, increments its own `version`, sets the linked
    fill's `claim_status` to `REJECTED` and its `status` from `PA_REFERRAL` to
    `CANCELLED`, and recomputes the parent prescription's `refills_remaining`."

    Design: Difficulty/compensating_invariant/pa_deny_conserves_refills_remaining_count
    """
    fx.set_clock()
    plan = fx.create_plan(bin="610017", pcn="PQ", name="Plan Q", copay_pct=0.10,
                          copay_max_cents=10000, refill_too_soon_threshold_pct=0.50)
    drug = fx.create_drug(ndc="00000-0017-01", name="Papa PA", unit_price_cents=500,
                          pa_required=True)
    fx.create_formulary(plan["id"], drug["id"], tier=4, allowed_amount_cents=400)
    patient = fx.create_patient(plan_id=plan["id"], full_name="Pat Eighteen",
                                date_of_birth="1996-06-06")
    prescriber = fx.create_prescriber(full_name="Dr Q", npi="1000000170")
    rx = fx.create_prescription(patient["id"], prescriber["id"], drug["id"],
                                quantity_per_fill=30, days_supply=30,
                                refills_authorized=2)
    # Original fill: PA approve, resubmit, then dispense.
    f1 = fx.create_fill_at_adjudicating(rx["id"])
    fx.submit_claim(f1["id"], rx["id"])  # -> PA_REFERRAL
    pa1 = fx.get_pa_for_fill(f1["id"])
    fx.approve_pa(pa1["id"], pa1["version"])  # cycle back to ADJUDICATING
    fx.submit_claim(f1["id"], rx["id"])  # -> READY_FILL (approved PA suppresses re-referral)
    validate_success(api.stage_will_call(f1["id"], TECH))
    # final_copay_cents = round_half_up(allowed_total * copay_pct) clamped:
    # allowed_total = allowed_amount_cents(400) * quantity_dispensed(30) +
    # dispensing_fee_cents(default 100) = 12100; raw = round(12100 * 0.10) = 1210;
    # min(max(1210, copay_min=0), copay_max=10000 - prior_oop=0) = 1210.
    fx.pay_for_fill(f1["id"], 1210)
    validate_success(api.dispense(f1["id"], PHARM))
    rx_after_first = validate_success(api.get_prescription(rx["id"], TECH))
    refills_after_first = rx_after_first["refills_remaining"]
    # Advance clock past too-soon, create refill -> PA referral.
    fx.set_clock("2026-01-20T00:00:00.000Z")
    f2 = fx.create_fill_at_adjudicating(rx["id"])
    fx.submit_claim(f2["id"], rx["id"])  # -> PA_REFERRAL
    pa2 = fx.get_pa_for_fill(f2["id"])
    denied = fx.deny_pa(pa2["id"], pa2["version"])
    assert denied["status"] == "DENIED"
    fill2 = validate_success(api.get_fill(f2["id"], PHARM))
    assert fill2["status"] == "CANCELLED"
    rx_after_deny = validate_success(api.get_prescription(rx["id"], PHARM))
    assert rx_after_deny["refills_remaining"] == 2
    assert rx_after_deny["refills_remaining"] == refills_after_first


# ---------------------------------------------------------------------------
# Queue A — depth-2 cascade: discontinue cancels ENTERED fill + recomputes refills
# ---------------------------------------------------------------------------
def test_discontinue_prescription_cascades_entered_fill_to_cancelled(api):
    """PRD §3.3: "On discontinuation the prescription transitions to
    `DISCONTINUED` and, cascading downward, every fill still in `ENTERED` is
    moved to `CANCELLED`."
    PRD §3.3: "A fill counts as consuming when its workflow status is one of
    `ADJUDICATING`, `PA_REFERRAL`, `READY_FILL`, `WILL_CALL`, or `DISPENSED`,
    excluding the original fill whose `fill_sequence` is 1; fills in `ENTERED`,
    `DUR_REVIEW`, `CANCELLED`, or `RETURNED_TO_STOCK` do not count toward
    consumption."

    Design: Difficulty/transitive_cascade/discontinue_prescription_cascades_entered_fill_to_cancelled
    """
    fx.set_clock()
    plan = fx.create_plan(bin="610008", pcn="PH", name="Plan H",
                          copay_pct=0.10, copay_max_cents=10000)
    drug = fx.create_drug(ndc="00000-0008-01", name="Golf", unit_price_cents=500)
    fx.create_formulary(plan["id"], drug["id"], tier=2, allowed_amount_cents=400)
    patient = fx.create_patient(plan_id=plan["id"], full_name="Pat Eight",
                                date_of_birth="1995-09-09")
    prescriber = fx.create_prescriber(full_name="Dr H", npi="1000000008")
    rx = fx.create_prescription(patient["id"], prescriber["id"], drug["id"],
                                quantity_per_fill=30, days_supply=30,
                                refills_authorized=2)
    fill = fx.create_fill(rx["id"])  # stays ENTERED
    validate_success(api.discontinue_prescription(rx["id"], PHARM))
    refreshed_fill = validate_success(api.get_fill(fill["id"], PHARM))
    refreshed_rx = validate_success(api.get_prescription(rx["id"], PHARM))
    assert refreshed_rx["status"] == "DISCONTINUED"
    assert refreshed_fill["status"] == "CANCELLED"
    assert refreshed_rx["refills_remaining"] == 2  # ENTERED fill never consumed


def test_discontinue_sets_status_then_cancels_each_entered_fill(api):
    """PRD §3.3: "A pharmacist may discontinue an `ACTIVE` prescription; this
    requires the prescription to currently be `ACTIVE` (otherwise
    `ERR_PRESCRIPTION_NOT_ACTIVE`)".
    PRD §3.3: "On discontinuation the prescription transitions to `DISCONTINUED`
    and, cascading downward, every fill still in `ENTERED` is moved to
    `CANCELLED`."

    Design: Difficulty/transitive_cascade/discontinue_prescription_cascades_entered_fill_to_cancelled
    """
    # Two ENTERED fills on the same prescription must BOTH cascade to CANCELLED.
    fx.set_clock()
    plan = fx.create_plan(bin="610038", pcn="PH2", name="Plan H2",
                          copay_pct=0.10, copay_max_cents=10000)
    drug = fx.create_drug(ndc="00000-0038-01", name="Golf2", unit_price_cents=500)
    fx.create_formulary(plan["id"], drug["id"], tier=2, allowed_amount_cents=400)
    patient = fx.create_patient(plan_id=plan["id"], full_name="Pat H2",
                                date_of_birth="1995-09-09")
    prescriber = fx.create_prescriber(full_name="Dr H2", npi="1000000380")
    rx = fx.create_prescription(patient["id"], prescriber["id"], drug["id"],
                                quantity_per_fill=30, days_supply=30,
                                refills_authorized=3)
    f1 = fx.create_fill(rx["id"])  # ENTERED original
    f2 = fx.create_fill(rx["id"])  # ENTERED refill (refills_remaining > 0)
    validate_success(api.discontinue_prescription(rx["id"], PHARM))
    assert validate_success(api.get_prescription(rx["id"], PHARM))["status"] == "DISCONTINUED"
    assert validate_success(api.get_fill(f1["id"], PHARM))["status"] == "CANCELLED"
    assert validate_success(api.get_fill(f2["id"], PHARM))["status"] == "CANCELLED"


def test_pa_deny_cancels_fill_and_rejects_claim(api):
    """PRD §3.10: "sets the linked fill's `claim_status` to `REJECTED` and its
    `status` from `PA_REFERRAL` to `CANCELLED`, and recomputes the parent
    prescription's `refills_remaining`."

    Design: Difficulty/compensating_invariant/pa_deny_conserves_refills_remaining_count
    """
    # Deny a PA-referred ORIGINAL fill (no refill-budget nuance): the fill is
    # CANCELLED, its claim REJECTED, and refills_remaining recomputes to the
    # authorized count because the cancelled fill no longer consumes.
    s = fx.setup_pa_referral(
        plan_overrides={"bin": "610037", "pcn": "PQ2", "name": "Plan Q2",
                        "copay_pct": 0.10, "copay_max_cents": 10000},
        drug_overrides={"ndc": "00000-0037-01", "name": "Papa2 PA",
                        "unit_price_cents": 500, "pa_required": True},
        prescriber_overrides={"full_name": "Dr Q2", "npi": "1000000370"},
        refills_authorized=2,
    )
    pa = s["pa"]
    denied = fx.deny_pa(pa["id"], pa["version"])
    assert denied["status"] == "DENIED"
    fill = validate_success(api.get_fill(s["fill"]["id"], PHARM))
    assert fill["status"] == "CANCELLED"
    assert fill["claim_status"] == "REJECTED"
    rx = validate_success(api.get_prescription(s["rx"]["id"], PHARM))
    assert rx["refills_remaining"] == 2


# ---------------------------------------------------------------------------
# Queue B — PA expiry on approve
# ---------------------------------------------------------------------------
def test_pa_expired_on_approve(api):
    """PRD §3.10: "Approval requires the request to be `PENDING` (otherwise
    `ERR_PA_NOT_PENDING`), `current_utc` to be at or before its `expires_utc`
    (otherwise `ERR_PA_EXPIRED`)".

    Design: Corner/errors/pa_expired_on_approve
    """
    s = fx.setup_pa_referral(
        plan_overrides={"bin": "700015", "pcn": "CO", "name": "PaExp Plan",
                        "copay_pct": 0.10, "copay_max_cents": 10000},
        drug_overrides={"ndc": "77777-0026-01", "name": "PaExpDrug",
                        "unit_price_cents": 500, "pa_required": True},
        prescriber_overrides={"full_name": "Dr PaExp", "npi": "2000000034"},
        qty=10,
    )
    pa = s["pa"]
    fx.set_clock("2026-02-15T00:00:00.000Z")  # past submitted+30d
    resp = api.approve_prior_auth(pa["id"], approve_pa_payload(pa["version"]), PHARM)
    validate_error(resp, ApiErrorId.ERR_PA_EXPIRED.value)


# ---------------------------------------------------------------------------
# Queue B — OCC: stale prescription version on submit
# ---------------------------------------------------------------------------
def test_stale_prescription_version_explicit_412(api):
    """PRD §2.9: "When submitting a claim for a fill, the request must carry
    `expected_prescription_version` holding the client's last-observed `version`
    of the fill's parent prescription. If that value does not match the
    prescription's current `version`, the submission is rejected with
    `ERR_STALE_PRESCRIPTION_VERSION` (HTTP 412)."

    Design: Corner/errors/stale_prescription_version_explicit_412
    """
    fx.set_clock()
    plan = fx.create_plan(bin="700013", pcn="CM", name="Occ Plan", copay_pct=0.10,
                          copay_max_cents=10000, refill_too_soon_threshold_pct=0.0)
    drug = fx.create_drug(ndc="77777-0024-01", name="OccDrug", unit_price_cents=500)
    fx.create_formulary(plan["id"], drug["id"], tier=2, allowed_amount_cents=400)
    patient = fx.create_patient(plan_id=plan["id"], full_name="Occ P",
                                date_of_birth="1980-01-01")
    prescriber = fx.create_prescriber(full_name="Dr Occ", npi="2000000032")
    rx = fx.create_prescription(patient["id"], prescriber["id"], drug["id"],
                                quantity_per_fill=30, days_supply=30,
                                refills_authorized=2)
    v_before = fx.get_rx_version(rx["id"])
    # First fill submits successfully (bumps prescription.version).
    f1 = fx.create_fill_at_adjudicating(rx["id"])
    validate_success(api.submit_claim(f1["id"], submit_claim_payload(v_before), TECH))
    # Second fill carries the now-stale pre-bump version.
    f2 = fx.create_fill_at_adjudicating(rx["id"])
    resp = api.submit_claim(f2["id"], submit_claim_payload(v_before), TECH)
    validate_error(resp, ApiErrorId.ERR_STALE_PRESCRIPTION_VERSION.value)


# ---------------------------------------------------------------------------
# Queue B — OCC: stale PA version on approve
# ---------------------------------------------------------------------------
def test_stale_pa_version_on_approve_412(api):
    """PRD §2.9: "When approving a prior-authorization request, the request must
    carry `expected_priorauthrequest_version` holding the client's last-observed
    `version` of that prior-auth request. If it does not match the request's
    current `version`, the approval is rejected with `ERR_STALE_PA_VERSION`
    (HTTP 412)."

    Design: Corner/errors/stale_pa_version_on_approve_412
    """
    s = fx.setup_pa_referral(
        plan_overrides={"bin": "700014", "pcn": "CN", "name": "PaOcc Plan",
                        "copay_pct": 0.10, "copay_max_cents": 10000},
        drug_overrides={"ndc": "77777-0025-01", "name": "PaOccDrug",
                        "unit_price_cents": 500, "pa_required": True},
        prescriber_overrides={"full_name": "Dr PaOcc", "npi": "2000000033"},
        qty=10,
    )
    pa = s["pa"]
    stale_version = pa["version"]
    fx.approve_pa(pa["id"], stale_version)  # legitimately bumps version
    resp = api.approve_prior_auth(pa["id"], approve_pa_payload(stale_version), PHARM)
    validate_error(resp, ApiErrorId.ERR_STALE_PA_VERSION.value)


# ---------------------------------------------------------------------------
# Queue B — OCC observable increments on submit
# ---------------------------------------------------------------------------
def test_occ_version_increments_on_submit_claim(api):
    """PRD §3.6: "the system computes the copays described below, sets the fill's
    `claim_status` to `PAID`, and increments the prescription's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_submit_claim
    """
    fx.set_clock()
    plan = fx.create_plan(bin="700017", pcn="CQ", name="Ver Plan",
                          copay_pct=0.10, copay_max_cents=10000)
    drug = fx.create_drug(ndc="77777-0031-01", name="VerDrug", unit_price_cents=500)
    fx.create_formulary(plan["id"], drug["id"], tier=2, allowed_amount_cents=400)
    patient = fx.create_patient(plan_id=plan["id"], full_name="Ver P",
                                date_of_birth="1980-01-01")
    prescriber = fx.create_prescriber(full_name="Dr Ver", npi="2000000039")
    rx = fx.create_prescription(patient["id"], prescriber["id"], drug["id"],
                                quantity_per_fill=30, days_supply=30)
    fill = fx.create_fill_at_adjudicating(rx["id"])
    v_before = fx.get_rx_version(rx["id"])
    validate_success(api.submit_claim(fill["id"], submit_claim_payload(v_before), TECH))
    v_after = fx.get_rx_version(rx["id"])
    assert v_after == v_before + 1, \
        f"prescription.version must increment by 1, was {v_before} now {v_after}"
