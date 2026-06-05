"""Appeal negotiation loop, parcel sale cycle, grant cascade, and invariants.

Covers difficulty queue instances:
  non_linear_state_machine / appeal_cyclic_evidence_negotiation_loop
  non_linear_state_machine / parcel_active_sold_active_cycle
  transitive_cascade / appeal_grant_cascades_to_assessment_then_bill_depth3
  compensating_invariant / appeal_withdraw_restores_assessment_taxable_value
  cross_entity_state_dependency / assessment_finalize_blocked_by_open_appeal
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_taxpayer_headers,
    make_hearing_officer_headers,
    setup_under_review_appeal,
    setup_filed_appeal,
    setup_appeal_with_held_hearing,
    create_owner,
    create_open_roll,
    create_parcel,
    create_assessment,
)
from test_helpers import factories as f

ASSESSOR = TEST_USERS["assessor_headers"]


# ===========================================================================
# non_linear_state_machine / appeal_cyclic_evidence_negotiation_loop
# ===========================================================================
def test_appeal_evidence_loop_increments_round_and_returns_to_review(api):
    """PRD §3.6: "The officer may request more evidence, moving the appeal
    `UNDER_REVIEW → EVIDENCE_REQUESTED` and recording the supplied `counter_value` as the
    new `opinion_of_value`".
    PRD §3.6: "The petitioning taxpayer then submits evidence, moving the appeal
    `EVIDENCE_REQUESTED → UNDER_REVIEW` and incrementing `round_no` by 1".

    Design: Difficulty/non_linear_state_machine/appeal_cyclic_evidence_negotiation_loop
    """
    owner, roll, parcel, asmt, appeal, ho_id = setup_under_review_appeal(
        requested_taxable_value=80000, market_value=100000
    )
    ho = make_hearing_officer_headers(ho_id)
    validate_success(api.request_evidence(appeal["id"], {"counter_value": 95000}, ho))
    after = validate_success(api.submit_evidence(appeal["id"], make_taxpayer_headers(owner["id"])))
    assert after["status"] == "UNDER_REVIEW", \
        f"after submit-evidence the appeal returns to UNDER_REVIEW, got {after['status']}"
    assert after["round_no"] == 2, \
        f"round_no should increment 1 -> 2 on the return, got {after['round_no']}"
    assert after["opinion_of_value"] == 95000, \
        f"opinion_of_value should reflect the counter offer 95000, got {after['opinion_of_value']}"


def test_appeal_request_evidence_sets_opinion_of_value(api):
    """PRD §3.6: "The officer may request more evidence, moving the appeal
    `UNDER_REVIEW → EVIDENCE_REQUESTED` and recording the supplied `counter_value` as the
    new `opinion_of_value`; this is permitted only while `round_no` is below 3".

    Design: Difficulty/non_linear_state_machine/appeal_cyclic_evidence_negotiation_loop
    """
    owner, roll, parcel, asmt, appeal, ho_id = setup_under_review_appeal(
        requested_taxable_value=80000, market_value=100000
    )
    ho = make_hearing_officer_headers(ho_id)
    after = validate_success(api.request_evidence(appeal["id"], {"counter_value": 95000}, ho))
    assert after["status"] == "EVIDENCE_REQUESTED", \
        f"request-evidence moves to EVIDENCE_REQUESTED, got {after['status']}"
    assert after["opinion_of_value"] == 95000


# ===========================================================================
# non_linear_state_machine / parcel_active_sold_active_cycle
# ===========================================================================
def test_parcel_sold_then_sale_assessment_returns_to_active(api):
    """PRD §3.2: "Recording a sale moves the parcel from `ACTIVE` to `SOLD`, reassigns
    `owner_id` to the new owner, and resets `last_certified_capped_base` to 0".
    PRD §3.3: "When a `SALE` assessment is created against a sold parcel, that parcel
    transitions from `SOLD` back to `ACTIVE` as a side effect of the create."

    Design: Difficulty/non_linear_state_machine/parcel_active_sold_active_cycle
    """
    o1 = create_owner()
    o2 = create_owner()
    roll = create_open_roll()
    parcel = create_parcel(o1["id"])
    sold = validate_success(api.record_sale(parcel["id"], {"new_owner_id": o2["id"]}, ASSESSOR))
    assert sold["status"] == "SOLD"
    asmt = create_assessment(parcel["id"], roll["id"], 250000, reassessment_event="SALE")
    after = validate_success(api.get_parcel(parcel["id"], ASSESSOR))
    assert after["status"] == "ACTIVE", \
        f"SALE assessment should return parcel to ACTIVE, got {after['status']}"
    assert after["owner_id"] == o2["id"], \
        f"owner_id should be reassigned to buyer, got {after['owner_id']}"
    assert asmt["capped_base_value"] == 250000, \
        f"SALE rebases to full market 250000, got {asmt['capped_base_value']}"


def test_record_sale_moves_parcel_to_sold(api):
    """PRD §3.2: "Recording a sale moves the parcel from `ACTIVE` to `SOLD`, reassigns
    `owner_id` to the new owner, and resets `last_certified_capped_base` to 0 so the next
    year's assessment cannot inherit a stale cap."

    Design: Difficulty/non_linear_state_machine/parcel_active_sold_active_cycle
    """
    o1 = create_owner()
    o2 = create_owner()
    parcel = create_parcel(o1["id"])
    sold = validate_success(api.record_sale(parcel["id"], {"new_owner_id": o2["id"]}, ASSESSOR))
    assert sold["status"] == "SOLD"
    assert sold["owner_id"] == o2["id"]
    assert sold["last_certified_capped_base"] == 0


# ===========================================================================
# transitive_cascade / appeal_grant_cascades_to_assessment_then_bill_depth3
# ===========================================================================
def test_grant_cascades_to_assessment_then_bill(api):
    """PRD §3.6: "A **grant** moves the appeal `UNDER_REVIEW → GRANTED` and sets
    `determined_taxable_value` to the full `requested_taxable_value`, awarding the petition in
    its entirety."
    PRD §3.6: "When the appeal ends `SETTLED` or `GRANTED`, the value-lowering branch fires:
    the assessment's `appealed_value` is set to the appeal's `determined_taxable_value`, and
    its `final_taxable_value` is overwritten with that same determined value, so the bill will
    reflect the Board's decision rather than the original taxable value."
    PRD §3.8: "(Equivalently, the cents amount is the billed taxable value times the mill rate
    divided by 10, rounded half-up.)"

    Design: Difficulty/transitive_cascade/appeal_grant_cascades_to_assessment_then_bill_depth3
    """
    # Assessment final_taxable_value 100000 (SALE rebase, no exemptions), requested 80000,
    # mill_rate 10.0 -> bill at 80000 taxable = round(80000*10/10) = 80000 cents.
    owner, roll, parcel, asmt, appeal, hearing, ho_id = setup_appeal_with_held_hearing(
        requested_taxable_value=80000, market_value=100000
    )
    ho = make_hearing_officer_headers(ho_id)
    granted = validate_success(api.grant_appeal(appeal["id"], ho))
    assert granted["status"] == "GRANTED"
    assert granted["determined_taxable_value"] == 80000
    asmt_after = validate_success(api.get_assessment(asmt["id"], ASSESSOR))
    assert asmt_after["appealed_value"] == 80000, \
        f"grant should set appealed_value to 80000, got {asmt_after['appealed_value']}"
    assert asmt_after["final_taxable_value"] == 80000, \
        f"grant should overwrite final_taxable_value to 80000, got {asmt_after['final_taxable_value']}"
    validate_success(api.finalize_assessment(asmt["id"], ASSESSOR))
    bill = validate_success(api.issue_bill(asmt["id"], ASSESSOR), expected_status=201)
    assert bill["tax_amount_cents"] == 80000, \
        f"bill should reflect the granted 80000 taxable: round(80000*10/10)=80000, got {bill['tax_amount_cents']}"


def test_grant_requires_held_hearing(api):
    """PRD §3.6: "Both grant and deny require that a hearing on this appeal has already been
    held — a hearing in `HELD` status — and either decision attempted without one is refused
    with `ERR_NO_HELD_HEARING`."

    Design: Difficulty/transitive_cascade/appeal_grant_cascades_to_assessment_then_bill_depth3
    """
    owner, roll, parcel, asmt, appeal, ho_id = setup_under_review_appeal(
        requested_taxable_value=80000, market_value=100000
    )
    ho = make_hearing_officer_headers(ho_id)
    resp = api.grant_appeal(appeal["id"], ho)
    validate_error(resp, ApiErrorId.ERR_NO_HELD_HEARING)


# ===========================================================================
# compensating_invariant / appeal_withdraw_restores_assessment_taxable_value
# ===========================================================================
def test_withdraw_restores_assessment_taxable_value(api):
    """PRD §3.6: "When the appeal ends `DENIED` or `WITHDRAWN`, the no-change branch fires:
    `appealed_value` stays null and `final_taxable_value` remains the original `taxable_value`."
    PRD §3.6: "In both branches the assessment returns to `NOTICED`, where it can finally be
    finalized."

    Design: Difficulty/compensating_invariant/appeal_withdraw_restores_assessment_taxable_value
    """
    # Assessment taxable_value 100000 (SALE rebase, no exemptions), appeal accepted to review.
    owner, roll, parcel, asmt, appeal, ho_id = setup_under_review_appeal(
        requested_taxable_value=80000, market_value=100000
    )
    withdrawn = validate_success(api.withdraw_appeal(appeal["id"], make_taxpayer_headers(owner["id"])))
    assert withdrawn["status"] == "WITHDRAWN"
    asmt_after = validate_success(api.get_assessment(asmt["id"], ASSESSOR))
    assert asmt_after["appealed_value"] is None, \
        f"withdraw must leave appealed_value null, got {asmt_after['appealed_value']}"
    assert asmt_after["final_taxable_value"] == 100000, \
        f"final_taxable_value must remain 100000, got {asmt_after['final_taxable_value']}"
    assert asmt_after["status"] == "NOTICED", \
        f"assessment must return to NOTICED, got {asmt_after['status']}"


def test_withdrawn_appeal_is_terminal_and_assessment_finalizable(api):
    """PRD §3.6: "A taxpayer may also abandon the contest by withdrawing it, which moves the
    appeal to `WITHDRAWN`".
    PRD §3.6: "In both branches the assessment returns to `NOTICED`, where it can finally be
    finalized."

    Design: Difficulty/compensating_invariant/appeal_withdraw_restores_assessment_taxable_value
    """
    owner, roll, parcel, asmt, appeal, ho_id = setup_under_review_appeal(
        requested_taxable_value=80000, market_value=100000
    )
    validate_success(api.withdraw_appeal(appeal["id"], make_taxpayer_headers(owner["id"])))
    # The compensating restore returns the assessment to NOTICED so finalize now succeeds,
    # freezing final_taxable_value at the unchanged 100000.
    final = validate_success(api.finalize_assessment(asmt["id"], ASSESSOR))
    assert final["status"] == "FINAL"
    assert final["final_taxable_value"] == 100000, \
        f"finalized value must be the unchanged 100000, got {final['final_taxable_value']}"


# ===========================================================================
# cross_entity_state_dependency / assessment_finalize_blocked_by_open_appeal
# ===========================================================================
def test_finalize_blocked_while_appeal_open(api):
    """PRD §3.5: "Finalizing freezes the assessment. It is permitted only when no appeal on
    the assessment is currently open — that is, none is in `FILED`, `UNDER_REVIEW`, or
    `EVIDENCE_REQUESTED` — otherwise the finalize is refused with `ERR_OPEN_APPEAL_EXISTS`."

    Design: Difficulty/cross_entity_state_dependency/assessment_finalize_blocked_by_open_appeal
    """
    owner, roll, parcel, asmt, appeal = setup_filed_appeal(
        requested_taxable_value=80000, market_value=100000
    )
    resp = api.finalize_assessment(asmt["id"], ASSESSOR)
    validate_error(resp, ApiErrorId.ERR_OPEN_APPEAL_EXISTS)
    asmt_after = validate_success(api.get_assessment(asmt["id"], ASSESSOR))
    assert asmt_after["status"] == "UNDER_APPEAL", \
        f"assessment should remain UNDER_APPEAL, got {asmt_after['status']}"


def test_finalize_blocked_while_appeal_under_review(api):
    """PRD §3.5: "Finalizing freezes the assessment. It is permitted only when no appeal on
    the assessment is currently open — that is, none is in `FILED`, `UNDER_REVIEW`, or
    `EVIDENCE_REQUESTED` — otherwise the finalize is refused with `ERR_OPEN_APPEAL_EXISTS`."

    Design: Difficulty/cross_entity_state_dependency/assessment_finalize_blocked_by_open_appeal
    """
    # An UNDER_REVIEW appeal is also "open"; finalize must still be refused.
    owner, roll, parcel, asmt, appeal, ho_id = setup_under_review_appeal(
        requested_taxable_value=80000, market_value=100000
    )
    resp = api.finalize_assessment(asmt["id"], ASSESSOR)
    validate_error(resp, ApiErrorId.ERR_OPEN_APPEAL_EXISTS)
