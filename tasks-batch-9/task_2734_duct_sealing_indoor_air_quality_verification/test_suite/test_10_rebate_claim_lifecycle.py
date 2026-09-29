"""The inspector spot check, the return-for-correction detour and the payment."""

from test_helpers import (
    ADMIN_HEADERS,
    CLAIM_APPROVED,
    CLAIM_PAID,
    CLAIM_RETURNED_FOR_CORRECTION,
    CLAIM_SUBMITTED,
    ERR_CLAIM_INVALID_STATE,
    INSPECTOR_FAIL,
    INSPECTOR_HEADERS,
    INSPECTOR_PASS,
    INSPECTOR_PENDING,
    JOB_RETEST_REQUIRED,
    JOB_VERIFIED,
    QA_HEADERS,
    REPORT_CORRECTION_REQUIRED,
    REPORT_ISSUED,
    SEAL_STATUS_VERIFIED,
    WARRANTY_NOT_REGISTERED,
    assert_program_ledger,
    assert_program_ledger_identity,
    factories as f,
    fixtures as fx,
    normalize_to_cfm25,
    validate_error,
    validate_success,
    variance_pct,
)


def test_a_returned_claim_comes_back_to_submitted_with_its_money_untouched(api):
    """The return cycle re-commits the amount frozen at first submission.

    PRD 3.8: "Resubmission recomputes **nothing**: `per_cfm_candidate_cents`,
    `percent_of_invoice_candidate_cents`, `basis_applied`, `tier_bonus_pct`,
    `capped_subtotal_cents`, `admin_fee_cents` and `payable_cents` all stay exactly as
    they were frozen at first submission. What does change: the claim returns to
    `SUBMITTED`, `resubmission_count` rises by 1, `documentation_bundle_ref` is
    replaced with the corrected reference, `inspector_outcome` resets to `PENDING`
    ... `committed` returns to true".

    Design: Difficulty/non_linear_state_machine/rebate_claim_returned_for_correction_resubmit_cycle
    """
    sc = fx.scenario_submitted_claim(api)
    assert sc.claim["payable_cents"] == 307230
    assert sc.claim["resubmission_count"] == 0

    returned = fx.record_spot_check(sc, spot_check_leakage_cfm=61.0)
    assert returned["inspector_outcome"] == INSPECTOR_FAIL
    assert returned["status"] == CLAIM_RETURNED_FOR_CORRECTION
    assert returned["committed"] is False

    reissued = validate_success(
        api.issue_verification_report(
            sc.report_id, f.issue_payload(signature_note="corrected and re-issued"),
            QA_HEADERS,
        )
    )
    assert reissued["status"] == REPORT_ISSUED
    assert reissued["correction_round"] == 1

    resubmitted = validate_success(
        api.resubmit_rebate_claim(sc.claim_id, f.resubmit_payload(), ADMIN_HEADERS)
    )
    assert resubmitted["status"] == CLAIM_SUBMITTED
    assert resubmitted["resubmission_count"] == 1
    assert resubmitted["documentation_bundle_ref"] == "BUNDLE-77-REV2"
    assert resubmitted["payable_cents"] == 307230
    assert resubmitted["per_cfm_candidate_cents"] == 294000
    assert resubmitted["percent_of_invoice_candidate_cents"] == 144000
    assert resubmitted["tier_bonus_pct"] == 0.10
    assert resubmitted["capped_subtotal_cents"] == 323400
    assert resubmitted["admin_fee_cents"] == 16170
    assert resubmitted["inspector_outcome"] == INSPECTOR_PENDING
    assert resubmitted["inspector_variance_pct"] is None
    assert resubmitted["spot_check_cfm25"] is None
    assert resubmitted["spot_check_leakage_cfm"] is None
    assert resubmitted["spot_check_pressure_pa"] is None
    assert resubmitted["inspector_user_id"] is None
    assert resubmitted["committed"] is True

    report = sc.read_report()
    assert report["status"] == REPORT_ISSUED
    assert report["correction_round"] == 1

    job = sc.read_seal_job()
    assert job["status"] == JOB_VERIFIED
    assert job["warranty_suspended"] is False

    program = sc.read_program()
    assert_program_ledger(program, 307230, 0, 4692770)
    assert_program_ledger_identity(program)


def test_the_return_cycle_can_be_walked_twice_without_moving_the_money(api):
    """A second detour raises both counters again and still freezes the same amount.

    PRD 3.8: "Resubmission closes the return cycle and is an administrator action. It
    is legal only from `RETURNED_FOR_CORRECTION`, and only once the underlying report
    has been re-issued — the report's status must read `ISSUED` again." And: "Hop two,
    caused by hop one, moves the linked verification report from `ISSUED` to
    `CORRECTION_REQUIRED` and raises its `correction_round` by 1."

    Design: Difficulty/non_linear_state_machine/rebate_claim_returned_for_correction_resubmit_cycle
    """
    sc = fx.scenario_submitted_claim(api)

    for expected_round in (1, 2):
        fx.record_spot_check(sc, spot_check_leakage_cfm=61.0)
        assert sc.read_claim()["status"] == CLAIM_RETURNED_FOR_CORRECTION
        assert sc.read_report()["correction_round"] == expected_round
        assert sc.read_report()["status"] == REPORT_CORRECTION_REQUIRED

        validate_success(
            api.issue_verification_report(
                sc.report_id, f.issue_payload(), QA_HEADERS
            )
        )
        resubmitted = validate_success(
            api.resubmit_rebate_claim(
                sc.claim_id,
                f.resubmit_payload(
                    documentation_bundle_ref=f"BUNDLE-77-REV{expected_round + 1}"
                ),
                ADMIN_HEADERS,
            )
        )
        assert resubmitted["resubmission_count"] == expected_round
        assert resubmitted["payable_cents"] == 307230

    final_claim = sc.read_claim()
    assert final_claim["status"] == CLAIM_SUBMITTED
    assert final_claim["resubmission_count"] == 2
    assert final_claim["documentation_bundle_ref"] == "BUNDLE-77-REV3"
    assert final_claim["payable_cents"] == 307230
    assert sc.read_report()["correction_round"] == 2
    assert sc.read_seal_job()["status"] == JOB_VERIFIED
    assert_program_ledger(sc.read_program(), 307230, 0, 4692770)


def test_a_failing_spot_check_cascades_three_hops_and_suspends_the_warranty(api):
    """Claim, report and run all move; the duct system deliberately does not.

    PRD 3.8: "Hop one stores the spot-check fields with `inspector_outcome` at `FAIL`,
    moves the claim from `SUBMITTED` to `RETURNED_FOR_CORRECTION`, sets `committed`
    false and releases `payable_cents` from the program's `committed_rebate_cents` so
    `remaining_budget_cents` rises by that amount. Hop two ... moves the linked
    verification report from `ISSUED` to `CORRECTION_REQUIRED` and raises its
    `correction_round` by 1. Hop three ... moves that report's sealing run from
    `VERIFIED` to `RETEST_REQUIRED` and sets its `warranty_suspended` true ... the duct
    system's `seal_status` stays at `VERIFIED`".

    Design: Difficulty/transitive_cascade/inspector_failure_cascade_depth_three
    """
    sc = fx.scenario_submitted_claim(api)
    assert_program_ledger(sc.read_program(), 307230, 0, 4692770)

    claim = fx.record_spot_check(sc, spot_check_leakage_cfm=61.0, spot_check_pressure_pa=25.0)
    assert claim["spot_check_cfm25"] == normalize_to_cfm25(61.0, 25.0)
    assert claim["spot_check_cfm25"] == 61.00
    assert claim["inspector_variance_pct"] == variance_pct(61.00, 55.00)
    assert claim["inspector_variance_pct"] == 10.91
    assert claim["inspector_outcome"] == INSPECTOR_FAIL
    assert claim["status"] == CLAIM_RETURNED_FOR_CORRECTION
    assert claim["committed"] is False
    assert claim["payable_cents"] == 307230

    program = sc.read_program()
    assert_program_ledger(program, 0, 0, 5000000)
    assert_program_ledger_identity(program)

    report = sc.read_report()
    assert report["status"] == REPORT_CORRECTION_REQUIRED
    assert report["correction_round"] == 1

    job = sc.read_seal_job()
    assert job["status"] == JOB_RETEST_REQUIRED
    assert job["warranty_suspended"] is True
    assert job["warranty_status"] == WARRANTY_NOT_REGISTERED

    assert sc.read_duct_system()["seal_status"] == SEAL_STATUS_VERIFIED


def test_a_variance_of_exactly_ten_percent_is_a_pass_and_approves_the_claim(api):
    """The tolerance comparison is strict, so equality approves rather than returns.

    PRD 3.8: "`inspector_outcome` becomes `FAIL` when `inspector_variance_pct` is
    strictly above 10.00 percent and `PASS` otherwise; a variance of exactly 10.00 is a
    pass." And: "A passing spot check moves the claim from `SUBMITTED` to `APPROVED`
    and leaves the commitment exactly as it was: `committed` stays true and the
    program's `committed_rebate_cents` is unchanged."

    Design: Difficulty/transitive_cascade/inspector_failure_cascade_depth_three
    """
    sc = fx.scenario_submitted_claim(api)
    claim = fx.record_spot_check(
        sc, spot_check_leakage_cfm=60.5, spot_check_pressure_pa=25.0
    )
    assert claim["spot_check_cfm25"] == 60.50
    assert claim["inspector_variance_pct"] == variance_pct(60.50, 55.00)
    assert claim["inspector_variance_pct"] == 10.00
    assert claim["inspector_outcome"] == INSPECTOR_PASS
    assert claim["status"] == CLAIM_APPROVED
    assert claim["committed"] is True

    assert_program_ledger(sc.read_program(), 307230, 0, 4692770)
    assert sc.read_report()["status"] == REPORT_ISSUED
    assert sc.read_report()["correction_round"] == 0
    job = sc.read_seal_job()
    assert job["status"] == JOB_VERIFIED
    assert job["warranty_suspended"] is False


def test_payment_transfers_the_commitment_and_leaves_the_balance_alone(api):
    """Pay is legal only from `APPROVED`, and the budget does not move a second time.

    PRD 3.8: "Payment is the last step and is legal only from `APPROVED`; attempted
    anywhere else it is `ERR_CLAIM_INVALID_STATE` ... moves the claim to the terminal
    `PAID` status, sets `committed` false, subtracts `payable_cents` from the program's
    `committed_rebate_cents` and adds it to `paid_rebate_cents` — so
    `remaining_budget_cents` does not move".

    Design: Corner/endpoints/paying_a_claim_moves_the_commitment_into_paid_without_touching_remaining
    """
    sc = fx.scenario_submitted_claim(api)
    assert sc.claim["payable_cents"] == 307230
    assert sc.claim["payment_reference"] is None
    assert_program_ledger(sc.read_program(), 307230, 0, 4692770)

    validate_error(
        api.pay_rebate_claim(sc.claim_id, f.pay_payload(), ADMIN_HEADERS),
        ERR_CLAIM_INVALID_STATE,
        409,
    )

    approved = validate_success(
        api.record_inspector_verification(
            sc.claim_id, f.inspector_verification_payload(), INSPECTOR_HEADERS
        )
    )
    assert approved["spot_check_cfm25"] == 57.00
    assert approved["inspector_variance_pct"] == variance_pct(57.00, 55.00)
    assert approved["inspector_variance_pct"] == 3.64
    assert approved["inspector_outcome"] == INSPECTOR_PASS
    assert approved["status"] == CLAIM_APPROVED

    paid = validate_success(
        api.pay_rebate_claim(sc.claim_id, f.pay_payload(), ADMIN_HEADERS)
    )
    assert paid["status"] == CLAIM_PAID
    assert paid["payment_reference"] == "ACH-90211"
    assert paid["committed"] is False
    assert paid["payable_cents"] == 307230

    program = sc.read_program()
    assert_program_ledger(program, 0, 307230, 4692770)
    assert_program_ledger_identity(program)

    # `PAID` is terminal.
    validate_error(
        api.pay_rebate_claim(sc.claim_id, f.pay_payload(), ADMIN_HEADERS),
        ERR_CLAIM_INVALID_STATE,
        409,
    )
