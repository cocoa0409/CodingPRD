"""Deficiency waiver variants, the deed-recording pipeline, the completion
cascade, and waiver rescission (PRD §3.2, §3.8)."""
from test_helpers import (
    ApiErrorId,
    assert_debt_conservation,
    assert_deed_recording,
    assert_deficiency_waiver,
    create_deed_recording_payload,
    get_agreement,
    get_case,
    get_deficiency_waiver,
    get_loan,
    set_clock,
    setup_case_at_agreement_active,
    setup_case_at_recording_pending,
    setup_case_at_recording_submitted,
    setup_completed_dil_case,
    validate_error,
    validate_success,
)


def test_deficiency_projected_at_acceptance(api):
    """Acceptance creates the DRAFT waiver with the forward-looking projection:
    accrual base + per-diem x 31 days to the agreed vacate date - FMV.

    PRD §3.5: "Acceptance bubbles up: the case moves from `TERMS_NEGOTIATION` to `AGREEMENT_ACTIVE` with a version increment, and for deed-in-lieu cases the system creates a DeficiencyWaiver in `DRAFT` status — its `case_id` set from the case, its `loan_id` copied from the case, and its `projected_waiver_cents` computed per the projected variant described in §3.8."
    PRD §3.8: "The projected variant — stored as `projected_waiver_cents` at creation — is forward-looking: count the whole days from the agreement's acceptance date to the agreed `vacate_date`, multiply that count by the loan's `per_diem_interest_cents`, add the accrual base, subtract the loan's `fair_market_value_cents`, and floor the result at zero."

    Design: Difficulty/dual_variant_calc/deficiency_projected_vs_final_divergence
    """
    bundle = setup_case_at_agreement_active(loan_number="LN-DV2")
    waiver = bundle["waiver"]
    assert waiver is not None, "deed-in-lieu acceptance must create the waiver"
    assert_deficiency_waiver(waiver)
    assert waiver["status"] == "DRAFT"
    assert waiver["case_id"] == bundle["case"]["id"]
    assert waiver["loan_id"] == bundle["loan"]["id"]
    # 20500000 accrual base + 3288 * 31 days (2026-08-01 -> 2026-09-01) - 18000000 FMV
    assert waiver["projected_waiver_cents"] == 2601928
    assert waiver["final_waiver_cents"] is None


def test_deficiency_final_diverges_at_recording(api):
    """The final variant accrues to the ACTUAL recordation date: recorded 4 days
    after the vacate date, the executed waiver is 2,615,080 vs the 2,601,928
    projection, and the loan's deficiency zeroes.

    PRD §3.8: "The final variant — stored as `final_waiver_cents` at execution — repeats the computation with the actual recordation date (the calendar date of the recording's `recorded_at`) in place of the vacate date."
    PRD §3.8: "The two variants legitimately diverge whenever recordation lands on a different date than the agreed vacate date."
    PRD §3.8: "Execution itself is not a client action: it arrives with the deed-recording confirmation described below, at which point `final_waiver_cents` is computed per the final variant, `pre_waiver_deficiency_cents` snapshots that final amount as the invariant base taken before zeroing, `waived_amount_cents` is set to `final_waiver_cents`, and the loan's `deficiency_balance_cents` drops to zero under the debt-conservation invariant (INV-DEBT)."

    Design: Difficulty/dual_variant_calc/deficiency_projected_vs_final_divergence
    """
    bundle = setup_completed_dil_case(
        loan_number="LN-DV2",
        instrument_number="INST-DV2",
        document_reference="DOC-DV2",
        handover_start="2026-09-05T10:00:00Z",
        handover_end="2026-09-05T11:00:00Z",
        submit_clock="2026-09-05T10:30:00Z",
        report_overrides={"broom_clean_verified": True, "keys_returned_count": 2, "line_items": []},
    )
    waiver = bundle["waiver"]
    assert waiver["status"] == "EXECUTED"
    assert waiver["projected_waiver_cents"] == 2601928, "projection recorded at acceptance stands"
    # recorded 2026-09-05: 20500000 + 3288 * 35 - 18000000
    assert waiver["final_waiver_cents"] == 2615080
    assert waiver["waived_amount_cents"] == 2615080
    loan = bundle["loan"]
    assert loan["deficiency_balance_cents"] == 0
    assert loan["status"] == "DEED_IN_LIEU_COMPLETED"
    assert loan["servicing_system_synced"] is True


def test_recording_confirm_cascade_recording_case(api):
    """Hop 1 and hop 2 of the confirmation cascade: the package is RECORDED with
    its instrument number, and the case completes.

    PRD §3.8: "Confirmation fires the completion cascade in hops. Hop one moves the case from `RECORDING_PENDING` to `COMPLETED`. Hop two rides case completion: the agreement moves from `ACCEPTED` to `COMPLETED`, the waiver executes as described above with its final amounts, and the loan moves from `WORKOUT_IN_PROGRESS` to `DEED_IN_LIEU_COMPLETED` with `servicing_system_synced` set to true."
    PRD §3.8: "A confirmation moves the package from `SUBMITTED` to `RECORDED`, stamps the county's `instrument_number` and the `recorded_at` logical timestamp, and is gated on two further preconditions beyond state: the case's deficiency waiver must be `DOCUMENTED` (`ERR_WAIVER_NOT_DOCUMENTED`), and the logical date at confirm must be no later than thirty days after the case's `handover_date` (`ERR_RECORDING_DEADLINE_PASSED`)."

    Design: Difficulty/transitive_cascade/recording_confirm_depth3_cascade
    """
    bundle = setup_completed_dil_case(
        loan_number="LN-TC1",
        instrument_number="INST-TC1",
        document_reference="DOC-TC1",
        loan_overrides={"foreclosure_referral_status": "REFERRED"},
    )
    recording = bundle["recording"]
    assert_deed_recording(recording)
    assert recording["status"] == "RECORDED"
    assert recording["instrument_number"] == "INST-TC1"
    assert recording["recorded_at"] is not None
    assert bundle["case"]["status"] == "COMPLETED"
    assert bundle["agreement"]["status"] == "COMPLETED"


def test_recording_confirm_cascade_waiver_loan(api):
    """Hop 3: the executed waiver carries its final amounts and the loan lands
    DEED_IN_LIEU_COMPLETED, synced, deficiency-free, with the referral withdrawn.

    PRD §3.8: "Hop three rides the waiver execution: the loan's `deficiency_balance_cents` becomes the snapshot minus the waived amount — zero, since the two are equal — and a loan whose `foreclosure_referral_status` was `REFERRED` has it withdrawn to `WITHDRAWN`."
    PRD §3.8: "Execution itself is not a client action: it arrives with the deed-recording confirmation described below, at which point `final_waiver_cents` is computed per the final variant, `pre_waiver_deficiency_cents` snapshots that final amount as the invariant base taken before zeroing, `waived_amount_cents` is set to `final_waiver_cents`, and the loan's `deficiency_balance_cents` drops to zero under the debt-conservation invariant (INV-DEBT)."

    Design: Difficulty/transitive_cascade/recording_confirm_depth3_cascade
    """
    bundle = setup_completed_dil_case(
        loan_number="LN-TC1",
        instrument_number="INST-TC1",
        document_reference="DOC-TC1",
        loan_overrides={"foreclosure_referral_status": "REFERRED"},
    )
    waiver = bundle["waiver"]
    assert waiver["status"] == "EXECUTED"
    # accepted 2026-08-01, recorded 2026-09-01: 20500000 + 3288 * 31 - 18000000
    assert waiver["final_waiver_cents"] == 2601928
    assert waiver["pre_waiver_deficiency_cents"] == 2601928
    assert waiver["waived_amount_cents"] == 2601928

    loan = bundle["loan"]
    assert loan["status"] == "DEED_IN_LIEU_COMPLETED"
    assert loan["servicing_system_synced"] is True
    assert loan["deficiency_balance_cents"] == 0
    assert loan["foreclosure_referral_status"] == "WITHDRAWN"
    assert_debt_conservation(loan, waiver)


def test_recording_deadline_passed(api, legal_counsel_headers):
    """Confirm more than thirty days after the handover date misses the recording
    deadline, even with the waiver documented.

    PRD §3.8: "A confirmation moves the package from `SUBMITTED` to `RECORDED`, stamps the county's `instrument_number` and the `recorded_at` logical timestamp, and is gated on two further preconditions beyond state: the case's deficiency waiver must be `DOCUMENTED` (`ERR_WAIVER_NOT_DOCUMENTED`), and the logical date at confirm must be no later than thirty days after the case's `handover_date` (`ERR_RECORDING_DEADLINE_PASSED`)."

    Design: Corner/validations/recording_deadline_passed_rejected
    """
    bundle = setup_case_at_recording_submitted(loan_number="LN-V15", document_reference="DOC-V15")
    assert bundle["case"]["handover_date"] == "2026-09-01"
    set_clock("2026-10-02T00:00:00Z")  # handover + 31 days; deadline was 2026-10-01

    resp = api.confirm_deed_recording(bundle["recording"]["id"], {"instrument_number": "INST-V15"},
                                      legal_counsel_headers)
    validate_error(resp, ApiErrorId.ERR_RECORDING_DEADLINE_PASSED.value)

    recording = validate_success(api.get_deed_recording(bundle["recording"]["id"], legal_counsel_headers))
    assert recording["status"] == "SUBMITTED"
    assert get_case(bundle["case"]["id"])["status"] == "RECORDING_PENDING"


def test_waiver_not_documented_blocks_confirm(api, legal_counsel_headers):
    """Documentation must precede recordation: confirming while the waiver is
    still DRAFT is refused.

    PRD §3.8: "A confirmation moves the package from `SUBMITTED` to `RECORDED`, stamps the county's `instrument_number` and the `recorded_at` logical timestamp, and is gated on two further preconditions beyond state: the case's deficiency waiver must be `DOCUMENTED` (`ERR_WAIVER_NOT_DOCUMENTED`), and the logical date at confirm must be no later than thirty days after the case's `handover_date` (`ERR_RECORDING_DEADLINE_PASSED`)."

    Design: Corner/validations/waiver_not_documented_blocks_confirm
    """
    bundle = setup_case_at_recording_pending(loan_number="LN-V16")
    # Waiver deliberately left in DRAFT.
    assert get_deficiency_waiver(bundle["waiver"]["id"])["status"] == "DRAFT"
    recording = validate_success(
        api.create_deed_recording(bundle["case"]["id"], create_deed_recording_payload(), legal_counsel_headers),
        201,
    )
    validate_success(api.submit_deed_recording(recording["id"], legal_counsel_headers))

    resp = api.confirm_deed_recording(recording["id"], {"instrument_number": "INST-V16"}, legal_counsel_headers)
    validate_error(resp, ApiErrorId.ERR_WAIVER_NOT_DOCUMENTED.value)
    recording = validate_success(api.get_deed_recording(recording["id"], legal_counsel_headers))
    assert recording["status"] == "SUBMITTED"


def test_recording_reject_allows_new_recording(api, legal_counsel_headers):
    """A county rejection is terminal only for the package: the case stays in
    RECORDING_PENDING and a fresh package can be created.

    PRD §3.8: "A rejection moves the package from `SUBMITTED` to `REJECTED` and preserves the supplied `rejection_reason`; the case itself remains in `RECORDING_PENDING`, and a fresh recording package may be created."

    Design: Corner/state_machines/recording_reject_allows_new_recording
    """
    bundle = setup_case_at_recording_submitted(loan_number="LN-S8", document_reference="DOC-S8")

    rejected = validate_success(
        api.reject_deed_recording(bundle["recording"]["id"], {"rejection_reason": "legal description mismatch"},
                                  legal_counsel_headers)
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["rejection_reason"] == "legal description mismatch"
    assert get_case(bundle["case"]["id"])["status"] == "RECORDING_PENDING"

    retry = validate_success(
        api.create_deed_recording(bundle["case"]["id"], create_deed_recording_payload(), legal_counsel_headers),
        201,
    )
    assert retry["status"] == "PENDING"
    assert retry["id"] != bundle["recording"]["id"]


def test_withdraw_from_recording_pending_rejected(api, specialist_headers):
    """Withdrawal is refused once the deed is in the recording pipeline.

    PRD §3.2: "Withdrawal — by the specialist, or by the borrower on their own case — is available from `INTAKE`, `ELIGIBILITY_REVIEW`, `MARKETING_PERIOD`, `TITLE_REVIEW`, `TERMS_NEGOTIATION`, `AGREEMENT_ACTIVE`, `VACATE_PENDING`, and `HOLDOVER_ESCALATED`, and is refused from `RECORDING_PENDING`, `EVICTION_IN_PROGRESS`, and every terminal state."
    PRD §3.2: "Any case action attempted from the wrong state is refused with `ERR_CASE_INVALID_STATE`."

    Design: Corner/validations/withdraw_from_recording_pending_rejected
    """
    bundle = setup_case_at_recording_pending(loan_number="LN-V17")
    assert bundle["case"]["status"] == "RECORDING_PENDING"

    resp = api.withdraw_case(bundle["case"]["id"], specialist_headers)
    validate_error(resp, ApiErrorId.ERR_CASE_INVALID_STATE.value)
    assert get_case(bundle["case"]["id"])["status"] == "RECORDING_PENDING"


def test_waiver_execute_amounts(api):
    """Execution snapshots the invariant base: waived == final == pre-waiver
    deficiency, and the loan's deficiency drops to zero.

    PRD §3.8: "Execution itself is not a client action: it arrives with the deed-recording confirmation described below, at which point `final_waiver_cents` is computed per the final variant, `pre_waiver_deficiency_cents` snapshots that final amount as the invariant base taken before zeroing, `waived_amount_cents` is set to `final_waiver_cents`, and the loan's `deficiency_balance_cents` drops to zero under the debt-conservation invariant (INV-DEBT)."

    Design: Difficulty/compensating_invariant/waiver_execute_rescind_conserves_debt
    """
    bundle = setup_completed_dil_case(loan_number="LN-CI2", instrument_number="INST-CI2",
                                      document_reference="DOC-CI2")
    waiver = bundle["waiver"]
    assert waiver["status"] == "EXECUTED"
    assert waiver["final_waiver_cents"] == 2601928
    assert waiver["pre_waiver_deficiency_cents"] == 2601928
    assert waiver["waived_amount_cents"] == 2601928
    assert bundle["loan"]["deficiency_balance_cents"] == 0
    assert_debt_conservation(bundle["loan"], waiver)


def test_waiver_rescind_restores_debt(api, workout_manager_headers):
    """Rescission is the compensating action of execution: the waived amount
    resets to zero and the loan's deficiency is restored to the snapshot.

    PRD §3.8: "Should the waiver later prove defective, a `WorkoutManager` may rescind an `EXECUTED` waiver — from any other state, `ERR_WAIVER_INVALID_STATE` — moving it to `RESCINDED`, resetting `waived_amount_cents` to zero, and restoring the loan's `deficiency_balance_cents` to `pre_waiver_deficiency_cents`, the compensating action of execution under INV-DEBT."

    Design: Difficulty/compensating_invariant/waiver_execute_rescind_conserves_debt
    """
    bundle = setup_completed_dil_case(loan_number="LN-CI2", instrument_number="INST-CI2",
                                      document_reference="DOC-CI2")
    waiver_id = bundle["waiver"]["id"]
    assert bundle["loan"]["deficiency_balance_cents"] == 0

    rescinded = validate_success(api.rescind_deficiency_waiver(waiver_id, workout_manager_headers))
    assert rescinded["status"] == "RESCINDED"
    assert rescinded["waived_amount_cents"] == 0
    assert rescinded["pre_waiver_deficiency_cents"] == 2601928

    loan = get_loan(bundle["loan"]["id"])
    assert loan["deficiency_balance_cents"] == 2601928, (
        f"deficiency must be restored to the pre-waiver snapshot, got {loan['deficiency_balance_cents']}"
    )
    assert_debt_conservation(loan, get_deficiency_waiver(waiver_id))
