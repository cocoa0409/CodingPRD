"""Cross-entity state dependencies and clinical gates (PRD §3.8, §3.9, §3.3)."""
from test_helpers import (
    validate_success, validate_error,
    setup_plan_approved, create_financing, setup_case_active,
    setup_refinement_requested,
    create_patient, create_case, add_usable_intake,
    create_clinician, add_assessed_checkin,
    api_client, TEST_USERS, make_patient_headers,
)

BILLING = TEST_USERS["billing_headers"]
MFG = TEST_USERS["manufacturing_headers"]


# ── case activate requires financing active (TreatmentCase -> FinancingPlan) ──
def test_activate_blocked_when_financing_still_pending(api):
    """PRD §3.8: "Activating a case moves it from `PLAN_APPROVED` to `ACTIVE` and
    is permitted only when the money side is settled - that is, the case has a
    financing plan whose `billing_state` is `ACTIVE`, or the case's
    `amount_collected_cents` is at least its `total_contracted_cents`. An
    activation attempt that meets neither condition is rejected with
    `ERR_PAYMENT_NOT_SETTLED` (HTTP 422)."

    A PLAN_APPROVED case with a created-but-not-activated financing plan
    (PENDING_ACTIVATION, nothing collected) cannot activate.

    Design: Difficulty/cross_entity_state_dependency/case_activate_requires_financing_active
    """
    ctx = setup_plan_approved(proposed_step_count=10, list_price_cents=375000)
    assert ctx["case"]["total_contracted_cents"] == 300000
    create_financing(ctx["case"]["id"], term_months=12, down_payment_cents=0, apr_bps=0)
    res = api.activate_case(ctx["case"]["id"], MFG)
    validate_error(res, "ERR_PAYMENT_NOT_SETTLED", expected_status=422)
    case = validate_success(api.get_case(ctx["case"]["id"], BILLING), 200)
    assert case["status"] == "PLAN_APPROVED", case["status"]


def test_activate_blocked_when_no_financing_and_nothing_collected(api):
    """PRD §3.8: "is permitted only when the money side is settled - that is, the
    case has a financing plan whose `billing_state` is `ACTIVE`, or the case's
    `amount_collected_cents` is at least its `total_contracted_cents`. An
    activation attempt that meets neither condition is rejected with
    `ERR_PAYMENT_NOT_SETTLED` (HTTP 422)."

    A PLAN_APPROVED case with no financing at all and amount_collected_cents 0
    (< total_contracted_cents) also fails the settled-money precondition.

    Design: Difficulty/cross_entity_state_dependency/case_activate_requires_financing_active
    """
    ctx = setup_plan_approved(proposed_step_count=10, list_price_cents=375000)
    assert ctx["case"]["amount_collected_cents"] == 0
    res = api.activate_case(ctx["case"]["id"], MFG)
    validate_error(res, "ERR_PAYMENT_NOT_SETTLED", expected_status=422)
    case = validate_success(api.get_case(ctx["case"]["id"], BILLING), 200)
    assert case["status"] == "PLAN_APPROVED", case["status"]


# ── refinement grant requires off-track check-in (Case/Refinement -> Checkin) ──
def test_refinement_grant_rejected_when_checkin_on_track(api):
    """PRD §3.9: "Granting a refinement re-opens an active case ... and is
    permitted only when the case is `ACTIVE`, the refinement is `REQUESTED`, and
    the triggering check-in belongs to this case and has a `tracking_assessment`
    of `OFF_TRACK`; a grant whose triggering check-in is not on this case or is
    not off-track is rejected with `ERR_REFINEMENT_NOT_JUSTIFIED` (HTTP 422)."

    A refinement citing an ON_TRACK check-in is not justified; the grant is
    rejected and the case stays ACTIVE.

    Design: Difficulty/cross_entity_state_dependency/refinement_grant_requires_offtrack_checkin
    """
    ctx = setup_refinement_requested(assessment="ON_TRACK", proposed_step_count=10)
    res = api.grant_refinement(ctx["refinement"]["id"], ctx["clin_headers"])
    validate_error(res, "ERR_REFINEMENT_NOT_JUSTIFIED", expected_status=422)
    case = validate_success(api.get_case(ctx["case"]["id"], BILLING), 200)
    assert case["status"] == "ACTIVE", case["status"]


def test_refinement_grant_rejected_when_checkin_pending(api):
    """PRD §3.9: "a grant whose triggering check-in is not on this case or is not
    off-track is rejected with `ERR_REFINEMENT_NOT_JUSTIFIED` (HTTP 422)."
    PRD §3.9: "A new check-in's `tracking_assessment` is `PENDING`."

    A refinement citing a never-assessed (PENDING) check-in is likewise not
    off-track, so the grant is rejected and the case stays ACTIVE.

    Design: Difficulty/cross_entity_state_dependency/refinement_grant_requires_offtrack_checkin
    """
    ctx = setup_case_active(proposed_step_count=10)
    from test_helpers import create_checkin_payload, create_refinement_payload
    chk = validate_success(
        api.create_checkin(ctx["case"]["id"], create_checkin_payload(reported_step_index=1),
                           ctx["pat_headers"]),
        201,
    )
    assert chk["tracking_assessment"] == "PENDING"
    ref = validate_success(
        api.create_refinement(
            create_refinement_payload(ctx["case"]["id"], chk["id"], additional_step_count=2),
            ctx["pat_headers"],
        ),
        201,
    )
    res = api.grant_refinement(ref["id"], ctx["clin_headers"])
    validate_error(res, "ERR_REFINEMENT_NOT_JUSTIFIED", expected_status=422)
    case = validate_success(api.get_case(ctx["case"]["id"], BILLING), 200)
    assert case["status"] == "ACTIVE", case["status"]


# ── empty usable-intake set blocks submit-for-review ──
def test_submit_for_review_blocked_by_subthreshold_intake(api):
    """PRD §3.3: "the case must hold at least one intake record whose `channel`
    equals the case's `intake_channel` and whose `quality_score` is at least the
    minimum usable quality of 0.60; if no intake meets that bar, the submission
    is rejected with `ERR_INTAKE_NOT_USABLE` (HTTP 422), because the images are
    clinically unusable."

    A case whose only intake scores 0.50 (below the 0.60 usability floor) has
    zero usable intakes and cannot leave INTAKE_PENDING.

    Design: Difficulty/boundary_precision_check/empty_intake_set_blocks_submit_for_review
    """
    create_clinician(license_state_codes=["CA"])
    patient = create_patient(state_code="CA")
    case = create_case(patient["id"], intake_channel="IMPRESSION_KIT", list_price_cents=300000)
    add_usable_intake(case["id"], patient["id"], channel="IMPRESSION_KIT", quality_score=0.5)
    res = api.submit_for_review(case["id"], make_patient_headers(patient["id"]))
    validate_error(res, "ERR_INTAKE_NOT_USABLE", expected_status=422)
    fetched = validate_success(api.get_case(case["id"], BILLING), 200)
    assert fetched["status"] == "INTAKE_PENDING", fetched["status"]


def test_submit_for_review_blocked_with_no_intake_records(api):
    """PRD §3.3: "the case must hold at least one intake record whose `channel`
    equals the case's `intake_channel` and whose `quality_score` is at least the
    minimum usable quality of 0.60; if no intake meets that bar, the submission
    is rejected with `ERR_INTAKE_NOT_USABLE` (HTTP 422)".

    The empty-collection edge: a case with no intake records at all has zero
    usable intakes, so submit-for-review is rejected and the case stays
    INTAKE_PENDING.

    Design: Difficulty/boundary_precision_check/empty_intake_set_blocks_submit_for_review
    """
    create_clinician(license_state_codes=["CA"])
    patient = create_patient(state_code="CA")
    case = create_case(patient["id"], intake_channel="IMPRESSION_KIT", list_price_cents=300000)
    res = api.submit_for_review(case["id"], make_patient_headers(patient["id"]))
    validate_error(res, "ERR_INTAKE_NOT_USABLE", expected_status=422)
    fetched = validate_success(api.get_case(case["id"], BILLING), 200)
    assert fetched["status"] == "INTAKE_PENDING", fetched["status"]
