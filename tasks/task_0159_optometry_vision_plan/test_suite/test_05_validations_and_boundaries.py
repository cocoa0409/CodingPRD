"""Business-rule validations, boundary precision, cross-entity state dependencies,
and validation-priority resolution.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    NON_EXISTENT_UUID,
    setup_active_rx,
    setup_clinic,
    setup_selfpay_dispensed_order,
    place_lab_order,
    issue_prescription,
    create_open_encounter,
    draft_claim,
    create_eligibility_payload,
    create_patient_payload,
)

FRONT_DESK = TEST_USERS["front_desk_headers"]
BILLER = TEST_USERS["biller_headers"]


# --------------------------------------------------------------------------- #
# Rule 5 — validation priority conflicts
# --------------------------------------------------------------------------- #
def test_state_check_beats_fiscal_on_double_cancel(api):
    """PRD §2.6: "State legality comes sixth: a resource that is not in a state from
    which the requested transition is legal yields `ERR_INVALID_STATE`. Only after these
    six gates are passed does the system evaluate the domain-specific business rules
    described throughout §2 and §3 ... benefit exhaustion."

    A cancel on an already-CANCELLED order fails the state gate (ERR_INVALID_STATE)
    before any benefit-fiscal rule runs.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_laborder_cancel_terminal
    """
    ctx = setup_active_rx(with_optician=True, patient_overrides={"plan_carrier": "VSP"},
                          elig=True, elig_overrides={"materials_allowance_cents": 21000})
    order = place_lab_order(ctx["rx"]["id"], ctx["opt_h"], eligibility_id=ctx["elig"]["id"],
                            expected_eligibility_version=ctx["elig_v0"], frame_charge_cents=15000,
                            lens_charge_cents=8000, frame_brand_tier="STANDARD")
    get_success_data(api.cancel_lab_order(order["id"], ctx["opt_h"]))

    res = api.cancel_lab_order(order["id"], ctx["opt_h"])
    validate_error(res, "ERR_INVALID_STATE")


def test_existence_check_beats_temporal_on_missing_claim(api):
    """PRD §2.6: "Path-resource existence comes third, yielding `ERR_NOT_FOUND`. ...
    Only after these six gates are passed does the system evaluate the domain-specific
    business rules described throughout §2 and §3 ... benefit-period and
    benefit-availability checks."

    Adjudicating a non-existent claim id fails the existence gate (ERR_NOT_FOUND)
    before any benefit-period temporal check could run.

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_safety_on_adjudicate_missing_claim
    """
    get_success_data(api.set_clock({"to_iso8601": "2026-06-01T00:00:00Z"}, FRONT_DESK))
    res = api.adjudicate_claim(NON_EXISTENT_UUID, BILLER)
    validate_error(res, "ERR_NOT_FOUND")


def test_state_check_beats_business_on_finalized_terminal_void(api):
    """PRD §2.6: "State legality comes sixth: a resource that is not in a state from
    which the requested transition is legal yields `ERR_INVALID_STATE`. Only after these
    six gates are passed does the system evaluate the domain-specific business rules."

    Voiding an encounter that is FINALIZED (terminal, not OPEN) fails the state gate
    with ERR_INVALID_STATE before the no-prescription business precondition is reached.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_laborder_cancel_terminal
    """
    from test_helpers import setup_finalized_routine_encounter
    ctx = setup_finalized_routine_encounter(
        elig=False, patient_overrides={"plan_carrier": "NONE"})
    res = api.void_encounter(ctx["enc"]["id"], FRONT_DESK)
    validate_error(res, "ERR_INVALID_STATE")


def test_existence_check_beats_business_on_missing_lab_order(api):
    """PRD §2.6: "Path-resource existence comes third, yielding `ERR_NOT_FOUND`. ...
    Only after these six gates are passed does the system evaluate the domain-specific
    business rules."

    Dispensing a non-existent lab-order id fails the path-existence gate (ERR_NOT_FOUND)
    before any prescription-dispensability business rule could run.

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_safety_on_adjudicate_missing_claim
    """
    from test_helpers import create_optician
    get_success_data(api.set_clock({"to_iso8601": "2026-06-01T00:00:00Z"}, FRONT_DESK))
    opt = create_optician()
    from test_helpers import make_optician_headers
    res = api.dispense_lab_order(
        NON_EXISTENT_UUID, {"dispensing_optician_id": opt["id"]}, make_optician_headers(opt["id"]))
    validate_error(res, "ERR_NOT_FOUND")


# --------------------------------------------------------------------------- #
# Rule 6 — boundary precision
# --------------------------------------------------------------------------- #
def test_remake_at_exactly_90_days_inside_window(api):
    """PRD §3.6: "Requesting a remake advances the order from `DISPENSED` to
    `REMAKE_REQUESTED` and is permitted only when the order is `DISPENSED`, when the
    current clock instant is no later than 90 days after `dispensed_at`, and when the
    order's `remake_count` is below the maximum of two completed remakes."

    Dispense at 2026-06-01, clock to exactly +90 days (2026-08-30): inside the window
    (no later than) so the remake succeeds.

    Design: Difficulty/boundary_precision_check/remake_window_exactly_90_days_inclusive_boundary
    """
    ctx = setup_selfpay_dispensed_order(clock="2026-06-01T00:00:00Z")
    get_success_data(api.set_clock({"to_iso8601": "2026-08-30T00:00:00Z"}, FRONT_DESK))

    remake = validate_success(api.request_lab_order_remake(
        ctx["order"]["id"], {"reason": "boundary"}, ctx["opt_h"]), 200)
    assert remake["status"] == "REMAKE_REQUESTED"


def test_empty_pool_zero_remaining_blocks_draw(api):
    """PRD §3.5: "the eligibility must be `ACTIVE` with materials remaining, since an
    `EXHAUSTED` period cannot start a new draw and is rejected with
    `ERR_BENEFIT_EXHAUSTED`."

    First order draws the full 21000 (pool remaining 0, eligibility EXHAUSTED); a second
    benefit-drawing order is rejected with ERR_BENEFIT_EXHAUSTED.

    Design: Difficulty/boundary_precision_check/empty_benefit_pool_zero_remaining_blocks_draw
    """
    ctx = setup_active_rx(with_optician=True, patient_overrides={"plan_carrier": "VSP"},
                          elig=True, elig_overrides={"materials_allowance_cents": 21000})
    rx_id, opt_h, elig_id = ctx["rx"]["id"], ctx["opt_h"], ctx["elig"]["id"]
    place_lab_order(rx_id, opt_h, eligibility_id=elig_id,
                    expected_eligibility_version=ctx["elig_v0"], frame_charge_cents=15000,
                    lens_charge_cents=8000, frame_brand_tier="STANDARD")
    elig_v1 = get_success_data(api.get_eligibility(elig_id, FRONT_DESK))["version"]

    res = api.create_lab_order({
        "prescription_id": rx_id,
        "eligibility_id": elig_id,
        "expected_eligibility_version": elig_v1,
        "frame_charge_cents": 9000,
        "lens_charge_cents": 5000,
        "frame_brand_tier": "STANDARD",
    }, opt_h)
    validate_error(res, "ERR_BENEFIT_EXHAUSTED")


def test_remake_at_91_days_outside_window_rejected(api):
    """PRD §3.6: "Requesting a remake advances the order from `DISPENSED` to
    `REMAKE_REQUESTED` and is permitted only when the order is `DISPENSED`, when the
    current clock instant is no later than 90 days after `dispensed_at` ... a request
    that falls outside the 90-day window ... is rejected with
    `ERR_REMAKE_WINDOW_CLOSED`."

    Dispense at 2026-06-01, clock to +91 days (2026-08-31): just outside the window, so
    the remake is rejected — the X+1 boundary.

    Design: Difficulty/boundary_precision_check/remake_window_exactly_90_days_inclusive_boundary
    """
    ctx = setup_selfpay_dispensed_order(clock="2026-06-01T00:00:00Z")
    get_success_data(api.set_clock({"to_iso8601": "2026-08-31T00:00:00Z"}, FRONT_DESK))

    res = api.request_lab_order_remake(ctx["order"]["id"], {"reason": "late"}, ctx["opt_h"])
    validate_error(res, "ERR_REMAKE_WINDOW_CLOSED")


def test_draw_at_remaining_above_zero_succeeds(api):
    """PRD §3.5: "the eligibility must be `ACTIVE` with materials remaining, since an
    `EXHAUSTED` period cannot start a new draw and is rejected with
    `ERR_BENEFIT_EXHAUSTED`."

    A pool with remaining_cents still above zero (allowance 40000, first draw 21000
    leaving 19000) accepts a second benefit draw — the non-exhausted side of the
    zero-remaining boundary.

    Design: Difficulty/boundary_precision_check/empty_benefit_pool_zero_remaining_blocks_draw
    """
    ctx = setup_active_rx(with_optician=True, patient_overrides={"plan_carrier": "VSP"},
                          elig=True, elig_overrides={"materials_allowance_cents": 40000})
    rx_id, opt_h, elig_id = ctx["rx"]["id"], ctx["opt_h"], ctx["elig"]["id"]
    place_lab_order(rx_id, opt_h, eligibility_id=elig_id,
                    expected_eligibility_version=ctx["elig_v0"], frame_charge_cents=15000,
                    lens_charge_cents=8000, frame_brand_tier="STANDARD")
    elig_v1 = get_success_data(api.get_eligibility(elig_id, FRONT_DESK))["version"]

    order2 = validate_success(api.create_lab_order({
        "prescription_id": rx_id,
        "eligibility_id": elig_id,
        "expected_eligibility_version": elig_v1,
        "frame_charge_cents": 9000,
        "lens_charge_cents": 5000,
        "frame_brand_tier": "STANDARD",
    }, opt_h), 201)
    assert order2["status"] == "PLACED"


# --------------------------------------------------------------------------- #
# Rule 7 — cross-entity state dependencies
# --------------------------------------------------------------------------- #
def test_dispense_blocked_by_non_dispensable_prescription(api):
    """PRD §3.6: "Dispensing is legal only from `IN_LAB`, and only while the referenced
    prescription is still `ACTIVE` and unexpired — otherwise
    `ERR_PRESCRIPTION_NOT_DISPENSABLE` applies."
    PRD §3.5: "If a lab order — whether at placement or at dispense — would be created or
    dispensed against a prescription that is `EXPIRED`, `SUPERSEDED`, or `REVOKED`, it is
    rejected with `ERR_PRESCRIPTION_NOT_DISPENSABLE`."

    An IN_LAB order whose prescription is SUPERSEDED between send-to-lab and dispense
    cannot be dispensed. (Revocation cannot be used to reach this state: per PRD §3.3
    "Revocation is permitted only when the prescription is `ACTIVE` and no lab order in
    `PLACED` or `IN_LAB` status references it" — so an IN_LAB order would block the
    revoke. Supersession, driven by issuing a fresh ACTIVE Rx of the identical rx_type,
    reaches the same non-dispensable terminal state without touching the order.)

    Design: Difficulty/cross_entity_state_dependency/dispense_requires_active_prescription_pair_laborder_prescription
    """
    ctx = setup_active_rx(with_optician=True, patient_overrides={"plan_carrier": "NONE"})
    pat_id, rx_id, opt_h, opt_id, od_h = (
        ctx["pat"]["id"], ctx["rx"]["id"], ctx["opt_h"], ctx["opt"]["id"], ctx["od_h"])
    order = place_lab_order(rx_id, opt_h, frame_charge_cents=15000, lens_charge_cents=8000)
    get_success_data(api.send_lab_order_to_lab(order["id"], opt_h))

    # Supersede the original ACTIVE EYEGLASS Rx by issuing another EYEGLASS Rx of the
    # identical rx_type from a fresh encounter (PRD §3.3) — moves rx_id to SUPERSEDED.
    enc2 = create_open_encounter(pat_id, ctx["od"]["id"])
    issue_prescription(pat_id, enc2["id"], od_h, rx_type="EYEGLASS",
                       sphere_od=-1.50, sphere_os=-1.25)
    assert get_success_data(api.get_prescription(rx_id, od_h))["status"] == "SUPERSEDED"

    res = api.dispense_lab_order(order["id"], {"dispensing_optician_id": opt_id}, opt_h)
    validate_error(res, "ERR_PRESCRIPTION_NOT_DISPENSABLE")


def test_second_routine_adjudicate_blocked_by_consumed_exam_benefit(api):
    """PRD §3.8: "for a routine claim it additionally requires the referenced
    eligibility to be in-period and its `exam_benefit_available` flag to be true, and a
    routine claim adjudicated when the exam benefit is no longer available is rejected
    with `ERR_BENEFIT_PERIOD_CLOSED`."

    Design: Difficulty/cross_entity_state_dependency/adjudicate_routine_requires_exam_benefit_available_pair_claim_eligibility
    """
    ctx = setup_clinic(with_optician=False, patient_overrides={"plan_carrier": "VSP"}, elig=True,
                       elig_overrides={"materials_allowance_cents": 40000})
    pat_id, od_h, elig_id = ctx["pat"]["id"], ctx["od_h"], ctx["elig"]["id"]

    # First routine claim adjudicated -> consumes the exam benefit.
    enc1 = create_open_encounter(pat_id, ctx["od"]["id"])
    issue_prescription(pat_id, enc1["id"], od_h)
    get_success_data(api.finalize_encounter(enc1["id"], od_h))
    claim1 = draft_claim(enc1["id"], eligibility_id=elig_id)
    get_success_data(api.adjudicate_claim(claim1["id"], BILLER))

    # Second routine claim on the same eligibility (exam_benefit_available now false).
    enc2 = create_open_encounter(pat_id, ctx["od"]["id"])
    issue_prescription(pat_id, enc2["id"], od_h, sphere_od=-1.50, sphere_os=-1.25)
    get_success_data(api.finalize_encounter(enc2["id"], od_h))
    claim2 = draft_claim(enc2["id"], eligibility_id=elig_id)

    res = api.adjudicate_claim(claim2["id"], BILLER)
    validate_error(res, "ERR_BENEFIT_PERIOD_CLOSED")


def test_dispense_succeeds_with_active_prescription(api):
    """PRD §3.6: "Dispensing is legal only from `IN_LAB`, and only while the referenced
    prescription is still `ACTIVE` and unexpired."

    An IN_LAB order whose prescription remains ACTIVE dispenses successfully — the
    in-bounds side of the LabOrder->Prescription state dependency.

    Design: Difficulty/cross_entity_state_dependency/dispense_requires_active_prescription_pair_laborder_prescription
    """
    ctx = setup_active_rx(with_optician=True, patient_overrides={"plan_carrier": "NONE"})
    rx_id, opt_h, opt_id = ctx["rx"]["id"], ctx["opt_h"], ctx["opt"]["id"]
    order = place_lab_order(rx_id, opt_h, frame_charge_cents=15000, lens_charge_cents=8000)
    get_success_data(api.send_lab_order_to_lab(order["id"], opt_h))

    dispensed = validate_success(api.dispense_lab_order(
        order["id"], {"dispensing_optician_id": opt_id}, opt_h), 200)
    assert dispensed["status"] == "DISPENSED"
    assert dispensed["dispensing_optician_id"] == opt_id


def test_first_routine_adjudicate_with_exam_benefit_available_succeeds(api):
    """PRD §3.8: "for a routine claim it additionally requires the referenced
    eligibility to be in-period and its `exam_benefit_available` flag to be true."
    PRD §3.8: "Adjudicating a routine claim also consumes the exam benefit: the
    eligibility's `exam_benefit_available` flag is set false."

    The first routine claim adjudicates while exam_benefit_available is still true, and
    that adjudication flips the flag false — the in-bounds side of the
    Claim->Eligibility dependency.

    Design: Difficulty/cross_entity_state_dependency/adjudicate_routine_requires_exam_benefit_available_pair_claim_eligibility
    """
    from test_helpers import setup_finalized_routine_encounter, draft_claim
    ctx = setup_finalized_routine_encounter(
        elig=True, patient_overrides={"plan_carrier": "VSP"},
        elig_overrides={"materials_allowance_cents": 40000})
    elig_id = ctx["elig"]["id"]
    assert get_success_data(api.get_eligibility(elig_id, FRONT_DESK))["exam_benefit_available"] is True

    claim = draft_claim(ctx["enc"]["id"], eligibility_id=elig_id)
    adj = validate_success(api.adjudicate_claim(claim["id"], BILLER), 200)
    assert adj["claim_status"] == "ADJUDICATED"
    assert get_success_data(api.get_eligibility(elig_id, FRONT_DESK))["exam_benefit_available"] is False


# --------------------------------------------------------------------------- #
# Rule 8 — resource temporal-overlap conflicts
# --------------------------------------------------------------------------- #
def test_new_eyeglass_rx_supersedes_prior_active(api):
    """PRD §3.3: "If the patient already holds an `ACTIVE` prescription of the identical
    `rx_type`, that older prescription is superseded — its status moves from `ACTIVE` to
    `SUPERSEDED` and its `version` is incremented — so that at most one active
    prescription of each type stands for a patient at any time."

    Design: Difficulty/resource_temporal_overlap/prescription_supersede_same_type_window_eyeglass
    """
    ctx = setup_active_rx(with_optician=False, patient_overrides={"plan_carrier": "NONE"})
    pat_id, od_h, rx1_id = ctx["pat"]["id"], ctx["od_h"], ctx["rx"]["id"]

    enc2 = create_open_encounter(pat_id, ctx["od"]["id"])
    rx2 = issue_prescription(pat_id, enc2["id"], od_h, rx_type="EYEGLASS",
                             sphere_od=-1.50, sphere_os=-1.25)

    rx1 = get_success_data(api.get_prescription(rx1_id, od_h))
    assert rx1["status"] == "SUPERSEDED"
    assert rx2["status"] == "ACTIVE"


def test_single_exam_slot_blocks_second_period_adjudication(api):
    """PRD §3.8: "for a routine claim it additionally requires the referenced
    eligibility to be in-period and its `exam_benefit_available` flag to be true, and a
    routine claim adjudicated when the exam benefit is no longer available is rejected
    with `ERR_BENEFIT_PERIOD_CLOSED`."

    Two routine exams in the same benefit period contend for the single exam slot; the
    second adjudication is blocked.

    Design: Difficulty/resource_temporal_overlap/benefit_period_overlap_single_exam_slot_eligibility
    """
    ctx = setup_clinic(clock="2026-03-01T00:00:00Z", with_optician=False,
                       patient_overrides={"plan_carrier": "VSP"}, elig=True,
                       elig_overrides={"materials_allowance_cents": 40000})
    pat_id, od_h, elig_id = ctx["pat"]["id"], ctx["od_h"], ctx["elig"]["id"]

    enc1 = create_open_encounter(pat_id, ctx["od"]["id"])
    issue_prescription(pat_id, enc1["id"], od_h, issue_date="2026-03-01")
    get_success_data(api.finalize_encounter(enc1["id"], od_h))
    claim1 = draft_claim(enc1["id"], eligibility_id=elig_id)
    get_success_data(api.adjudicate_claim(claim1["id"], BILLER))

    get_success_data(api.set_clock({"to_iso8601": "2026-09-01T00:00:00Z"}, FRONT_DESK))
    enc2 = create_open_encounter(pat_id, ctx["od"]["id"])
    issue_prescription(pat_id, enc2["id"], od_h, sphere_od=-1.50, sphere_os=-1.25,
                       issue_date="2026-09-01")
    get_success_data(api.finalize_encounter(enc2["id"], od_h))
    claim2 = draft_claim(enc2["id"], eligibility_id=elig_id)

    res = api.adjudicate_claim(claim2["id"], BILLER)
    validate_error(res, "ERR_BENEFIT_PERIOD_CLOSED")


def test_supersede_only_affects_same_rx_type(api):
    """PRD §3.3: "If the patient already holds an `ACTIVE` prescription of the identical
    `rx_type`, that older prescription is superseded — its status moves from `ACTIVE` to
    `SUPERSEDED` ... so that at most one active prescription of each type stands for a
    patient at any time."

    Issuing a CONTACT Rx does not supersede an existing ACTIVE EYEGLASS Rx — the
    type-exclusion window is per rx_type, so the prior EYEGLASS stays ACTIVE.

    Design: Difficulty/resource_temporal_overlap/prescription_supersede_same_type_window_eyeglass
    """
    ctx = setup_active_rx(with_optician=False, patient_overrides={"plan_carrier": "NONE"})
    pat_id, od_h, eyeglass_id = ctx["pat"]["id"], ctx["od_h"], ctx["rx"]["id"]

    enc2 = create_open_encounter(pat_id, ctx["od"]["id"])
    contact = issue_prescription(pat_id, enc2["id"], od_h, rx_type="CONTACT",
                                 sphere_od=-1.50, sphere_os=-1.25)

    eyeglass = get_success_data(api.get_prescription(eyeglass_id, od_h))
    assert eyeglass["status"] == "ACTIVE"
    assert contact["status"] == "ACTIVE"


def test_single_exam_slot_first_period_adjudication_succeeds(api):
    """PRD §3.4: "The `EXAM` pool represents the single routine-exam benefit slot for the
    period."
    PRD §3.8: "Adjudicating a routine claim also consumes the exam benefit: the
    eligibility's `exam_benefit_available` flag is set false and the `EXAM` pool is
    marked fully consumed by setting its `consumed_cents` to its `allotted_cents`."

    The first routine exam in a benefit period adjudicates and consumes the single exam
    slot (EXAM pool fully consumed) — the in-bounds side of the aggregate-capacity-1
    interval.

    Design: Difficulty/resource_temporal_overlap/benefit_period_overlap_single_exam_slot_eligibility
    """
    from test_helpers import setup_finalized_routine_encounter, draft_claim, get_exam_pool
    ctx = setup_finalized_routine_encounter(
        clock="2026-03-01T00:00:00Z", elig=True, patient_overrides={"plan_carrier": "VSP"},
        elig_overrides={"materials_allowance_cents": 40000},
        rx_overrides={"issue_date": "2026-03-01"})
    elig_id = ctx["elig"]["id"]
    claim = draft_claim(ctx["enc"]["id"], eligibility_id=elig_id)
    adj = validate_success(api.adjudicate_claim(claim["id"], BILLER), 200)
    assert adj["claim_status"] == "ADJUDICATED"

    exam_pool = get_exam_pool(elig_id)
    assert exam_pool["consumed_cents"] == exam_pool["allotted_cents"]


# --------------------------------------------------------------------------- #
# Corner — validations
# --------------------------------------------------------------------------- #
def test_carrier_mismatch_on_eligibility_create(api):
    """PRD §3.4: "the `carrier` underwriting it, which is one of `VSP` or `EYEMED` and
    must equal the patient's own `plan_carrier`, failing which the request is rejected
    with `ERR_CARRIER_MISMATCH`."

    Design: Corner/validations/carrier_mismatch_on_eligibility_create
    """
    get_success_data(api.set_clock({"to_iso8601": "2026-06-01T00:00:00Z"}, FRONT_DESK))
    pat = get_success_data(api.create_patient(
        create_patient_payload(full_name="Pat CM", plan_carrier="VSP"), FRONT_DESK))

    res = api.create_eligibility(
        create_eligibility_payload(pat["id"], carrier="EYEMED"), FRONT_DESK)
    validate_error(res, "ERR_CARRIER_MISMATCH")


def test_medical_billing_ineligible_non_h_complaint(api):
    """PRD §3.8: "A `Biller` bills a finalized visit by drafting a claim against its
    `encounter_id` ... A medical route is permitted only when the patient's
    `medical_insurance_on_file` is true and the encounter's `chief_complaint_code`
    begins with the letter H; a medical claim that fails either condition is rejected
    with `ERR_MEDICAL_BILLING_INELIGIBLE`."

    A MEDICAL_EYE encounter with a non-H chief complaint (Z01) yields a MEDICAL billing
    route that fails the H-code condition, so drafting the claim is rejected — the rule
    guards the draft, the operation §3.8 introduces it on.

    Design: Corner/validations/medical_billing_ineligible_non_h_complaint
    """
    from test_helpers import setup_finalized_routine_encounter, create_claim_payload
    ctx = setup_finalized_routine_encounter(
        elig=False,
        patient_overrides={"plan_carrier": "NONE", "medical_insurance_on_file": True},
        encounter_overrides={"encounter_type": "MEDICAL_EYE", "chief_complaint_code": "Z01",
                             "exam_fee_cents": 18000, "refraction_fee_cents": 0},
    )
    res = api.create_claim(create_claim_payload(ctx["enc"]["id"]), BILLER)
    validate_error(res, "ERR_MEDICAL_BILLING_INELIGIBLE")


def test_payment_exceeds_balance_rejected(api):
    """PRD §3.9: "A payment names an `amount_cents`, which must be greater than zero and
    must not exceed the remaining patient responsibility — that is, the
    `patient_responsibility_cents` minus the amount already in `settled_cents`; a
    payment that is zero or negative or that exceeds the remaining balance is rejected
    with `ERR_PAYMENT_EXCEEDS_BALANCE`."

    Design: Corner/validations/payment_exceeds_balance_rejected
    """
    from test_helpers import setup_adjudicated_routine_claim
    ctx = setup_adjudicated_routine_claim()
    res = api.pay_claim(ctx["claim"]["id"], {"amount_cents": 3000}, BILLER)
    validate_error(res, "ERR_PAYMENT_EXCEEDS_BALANCE")


def test_wrong_provider_role_on_encounter(api):
    """PRD §3.2: "Opening an encounter requires the `patient_id` being seen and the
    `provider_id` of the optometrist who will conduct the exam — and that referenced
    provider's `role` must be `OPTOMETRIST`, or the request is rejected with
    `ERR_WRONG_PROVIDER_ROLE`."

    Design: Corner/validations/wrong_provider_role_on_encounter
    """
    from test_helpers import create_optician
    get_success_data(api.set_clock({"to_iso8601": "2026-06-01T00:00:00Z"}, FRONT_DESK))
    optician = create_optician()
    pat = get_success_data(api.create_patient(
        create_patient_payload(full_name="Pat WP", plan_carrier="NONE"), FRONT_DESK))

    res = api.create_encounter({
        "patient_id": pat["id"],
        "provider_id": optician["id"],
        "encounter_type": "ROUTINE_VISION",
        "exam_fee_cents": 12000,
        "refraction_fee_cents": 3000,
    }, FRONT_DESK)
    validate_error(res, "ERR_WRONG_PROVIDER_ROLE")


def test_benefit_period_closed_out_of_period_draw(api):
    """PRD §3.5: "the eligibility must be in-period, failing which the order is rejected
    with `ERR_BENEFIT_PERIOD_CLOSED`."

    Design: Corner/validations/benefit_period_closed_out_of_period_draw
    """
    ctx = setup_active_rx(with_optician=True, patient_overrides={"plan_carrier": "VSP"},
                          elig=True, elig_overrides={"materials_allowance_cents": 40000,
                                                     "benefit_period_start": "2026-01-01"})
    # Advance clock past benefit_period_end (2026-01-01 + 12mo = 2027-01-01).
    get_success_data(api.set_clock({"to_iso8601": "2027-02-01T00:00:00Z"}, FRONT_DESK))
    res = api.create_lab_order({
        "prescription_id": ctx["rx"]["id"],
        "eligibility_id": ctx["elig"]["id"],
        "expected_eligibility_version": ctx["elig_v0"],
        "frame_charge_cents": 15000,
        "lens_charge_cents": 8000,
        "frame_brand_tier": "STANDARD",
    }, ctx["opt_h"])
    validate_error(res, "ERR_BENEFIT_PERIOD_CLOSED")


def test_expired_prescription_blocks_laborder_placement(api):
    """PRD §3.5: "Placing it requires the `prescription_id` being fulfilled, whose
    referenced prescription must be `ACTIVE` and not expired ... If a lab order — whether
    at placement or at dispense — would be created or dispensed against a prescription
    that is `EXPIRED`, `SUPERSEDED`, or `REVOKED`, it is rejected with
    `ERR_PRESCRIPTION_NOT_DISPENSABLE`, because lenses must match a current
    prescription."

    A CONTACT Rx (12-month expiry) expires once the clock passes its expiry_date.

    Design: Corner/state_machines/expired_prescription_blocks_laborder_placement
    """
    ctx = setup_active_rx(with_optician=True, patient_overrides={"plan_carrier": "NONE"},
                          rx_overrides={"rx_type": "CONTACT", "issue_date": "2026-06-01"})
    # Contact Rx issued 2026-06-01 expires 2027-06-01; advance past it.
    get_success_data(api.set_clock({"to_iso8601": "2027-07-01T00:00:00Z"}, FRONT_DESK))
    res = api.create_lab_order({
        "prescription_id": ctx["rx"]["id"],
        "frame_charge_cents": 15000,
        "lens_charge_cents": 8000,
        "frame_brand_tier": "STANDARD",
    }, ctx["opt_h"])
    validate_error(res, "ERR_PRESCRIPTION_NOT_DISPENSABLE")


def test_occ_stale_eligibility_version_rejected(api):
    """PRD §2.10: "The server compares this token to the eligibility's current
    `version`. If another writer has advanced the eligibility's `version` since the
    client last read it — for instance by placing an earlier benefit-drawing order that
    committed a materials draw, possibly exhausting the pool — the client's view of the
    remaining allowance is stale, and the create is rejected with
    `ERR_STALE_ELIGIBILITY_VERSION` at HTTP status 412, preventing a draw against an
    unobserved state."

    Design: Corner/errors/occ_stale_eligibility_version_rejected
    """
    ctx = setup_active_rx(with_optician=True, patient_overrides={"plan_carrier": "VSP"},
                          elig=True, elig_overrides={"materials_allowance_cents": 40000})
    rx_id, opt_h, elig_id, v0 = ctx["rx"]["id"], ctx["opt_h"], ctx["elig"]["id"], ctx["elig_v0"]
    # First draw bumps eligibility version, making v0 stale.
    place_lab_order(rx_id, opt_h, eligibility_id=elig_id, expected_eligibility_version=v0,
                    frame_charge_cents=9000, lens_charge_cents=5000, frame_brand_tier="STANDARD")

    res = api.create_lab_order({
        "prescription_id": rx_id,
        "eligibility_id": elig_id,
        "expected_eligibility_version": v0,
        "frame_charge_cents": 9000,
        "lens_charge_cents": 5000,
        "frame_brand_tier": "STANDARD",
    }, opt_h)
    validate_error(res, "ERR_STALE_ELIGIBILITY_VERSION")
