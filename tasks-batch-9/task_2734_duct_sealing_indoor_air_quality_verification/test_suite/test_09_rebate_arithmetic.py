"""The six pinned steps of the rebate arithmetic and the ledger they move."""

from test_helpers import (
    ADMIN_HEADERS,
    CLAIM_PAID,
    CLAIM_SUBMITTED,
    ERR_REBATE_CLAIM_NOT_FOUND,
    ERR_PROGRAM_BUDGET_EXCEEDED,
    ERR_REBATE_REDUCTION_BELOW_PROGRAM_MINIMUM,
    INSPECTOR_HEADERS,
    INSPECTOR_PENDING,
    NON_EXISTENT_UUID,
    REPORT_ISSUED,
    REBATE_BASIS_LESSER_OF_BOTH,
    REBATE_BASIS_PERCENT_OF_INVOICE,
    REBATE_BASIS_PER_CFM,
    assert_all_cents_integers,
    assert_program_ledger,
    assert_program_ledger_identity,
    expected_admin_fee_cents,
    expected_capped_subtotal_cents,
    expected_per_cfm_candidate_cents,
    expected_percent_of_invoice_candidate_cents,
    expected_tier_bonus_pct,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_the_lesser_of_both_basis_picks_the_smaller_candidate(api):
    """Both candidates are always computed; the smaller one becomes the base.

    PRD 3.8: "Step one computes both base candidates, and both are always computed and
    both are always persisted on the claim regardless of which one is used." And:
    "Under `LESSER_OF_BOTH` the base is whichever of the two candidates is smaller".

    Design: Difficulty/dual_variant_calc/rebate_basis_per_cfm_vs_percent_of_invoice_divergence
    """
    sc = fx.scenario_issued_report(
        api, program={"rebate_basis": REBATE_BASIS_LESSER_OF_BOTH}
    )
    assert sc.report["cfm_reduced_whole_house"] == 245.00

    claim = fx.submit_claim(sc)
    assert claim["per_cfm_candidate_cents"] == expected_per_cfm_candidate_cents(1200, 245.00)
    assert claim["per_cfm_candidate_cents"] == 294000
    assert claim["percent_of_invoice_candidate_cents"] == (
        expected_percent_of_invoice_candidate_cents(480000, 3000)
    )
    assert claim["percent_of_invoice_candidate_cents"] == 144000
    assert claim["basis_applied"] == REBATE_BASIS_PERCENT_OF_INVOICE

    assert claim["tier_bonus_pct"] == expected_tier_bonus_pct(81.67)
    assert claim["tier_bonus_pct"] == 0.10
    assert claim["capped_subtotal_cents"] == expected_capped_subtotal_cents(
        144000, 0.10, 500000
    )
    assert claim["capped_subtotal_cents"] == 158400
    assert claim["admin_fee_cents"] == expected_admin_fee_cents(158400)
    assert claim["admin_fee_cents"] == 7920
    assert claim["payable_cents"] == 150480
    assert claim["status"] == CLAIM_SUBMITTED
    assert claim["committed"] is True
    assert_all_cents_integers(claim)

    program = sc.read_program()
    assert_program_ledger(program, 150480, 0, 4849520)
    assert_program_ledger_identity(program)


def test_a_tie_between_the_two_candidates_resolves_to_per_cfm(api):
    """When the candidates are equal the per-CFM route wins the label.

    PRD 3.8: "`basis_applied` reads `PER_CFM` when the per-CFM candidate is less than
    or equal to the invoice candidate and `PERCENT_OF_INVOICE` only when the invoice
    candidate is strictly smaller — **ties resolve to `PER_CFM`**."

    Design: Difficulty/dual_variant_calc/rebate_basis_per_cfm_vs_percent_of_invoice_divergence
    """
    sc = fx.scenario_issued_report(
        api,
        program={"rebate_basis": REBATE_BASIS_LESSER_OF_BOTH},
        project={"invoice_amount_cents": 980000},
    )
    claim = fx.submit_claim(sc)
    assert claim["per_cfm_candidate_cents"] == 294000
    assert claim["percent_of_invoice_candidate_cents"] == 294000
    assert claim["basis_applied"] == REBATE_BASIS_PER_CFM
    assert claim["capped_subtotal_cents"] == 323400
    assert claim["admin_fee_cents"] == 16170
    assert claim["payable_cents"] == 307230


def test_the_cap_binds_before_the_administrative_fee_is_taken(api):
    """Capping first and then charging the fee is a smaller number than the reverse.

    PRD 3.8: "`capped_subtotal_cents` is then the smaller of that bonused subtotal and
    the program's `cap_cents`. `admin_fee_cents` is five percent of
    `capped_subtotal_cents`, rounded half-up to a whole number of cents — computed
    **after** the cap, never before ... Taking the administrative fee first and capping
    afterwards yields a different, larger number whenever the cap binds, and is wrong."

    Design: Difficulty/combinatorial_formula/rebate_cap_before_admin_fee_evaluation_order
    """
    sc = fx.scenario_issued_report(api, program={"cap_cents": 200000})
    claim = fx.submit_claim(sc)

    assert claim["per_cfm_candidate_cents"] == 294000
    assert claim["tier_bonus_pct"] == 0.10
    assert claim["capped_subtotal_cents"] == 200000
    assert claim["admin_fee_cents"] == expected_admin_fee_cents(200000)
    assert claim["admin_fee_cents"] == 10000
    assert claim["payable_cents"] == 190000
    # Fee first, cap afterwards would have paid the whole cap.
    assert claim["payable_cents"] != 200000

    program = sc.read_program()
    assert_program_ledger(program, 190000, 0, 4810000)
    assert_program_ledger_identity(program)


def test_a_cap_that_does_not_bind_leaves_the_bonused_subtotal_alone(api):
    """With room under the cap the fee is charged on the full bonused subtotal.

    PRD 3.8: "The bonused subtotal is the base multiplied by one plus
    `tier_bonus_pct`, rounded half-up to a whole number of cents. `capped_subtotal_cents`
    is then the smaller of that bonused subtotal and the program's `cap_cents`."

    Design: Difficulty/combinatorial_formula/rebate_cap_before_admin_fee_evaluation_order
    """
    sc = fx.scenario_issued_report(api)
    claim = fx.submit_claim(sc)

    assert claim["basis_applied"] == REBATE_BASIS_PER_CFM
    assert claim["capped_subtotal_cents"] == expected_capped_subtotal_cents(
        294000, 0.10, 500000
    )
    assert claim["capped_subtotal_cents"] == 323400
    assert claim["admin_fee_cents"] == 16170
    assert claim["payable_cents"] == 307230
    assert claim["inspector_outcome"] == INSPECTOR_PENDING
    assert claim["resubmission_count"] == 0
    assert claim["version"] == 1

    program = sc.read_program()
    assert_program_ledger(program, 307230, 0, 4692770)
    assert_program_ledger_identity(program)


def test_the_tier_bonus_band_is_inclusive_at_its_lower_edge(api):
    """Exactly 75.00 percent earns the ten-percent bonus, not the five-percent one.

    PRD 3.8: "`tier_bonus_pct` is 0.20 when `reduction_pct_whole_house_basis` is at
    least 90.00, otherwise 0.10 when it is at least 75.00, otherwise 0.05 when it is at
    least 60.00, and otherwise 0.00. Each band boundary is inclusive at its lower edge,
    so exactly 75.00 percent earns the 0.10 bonus rather than the 0.05 one."

    Design: Corner/calculations/rebate_tier_bonus_at_the_exact_seventy_five_percent_boundary
    """
    sc = fx.scenario_issued_report(
        api,
        program={"min_reduction_pct": 70.00},
        post={"measured_leakage_cfm": 75.0},
    )
    assert sc.report["reduction_pct_whole_house_basis"] == 75.00
    assert sc.report["cfm_reduced_whole_house"] == 225.00
    assert sc.report["guarantee_threshold_pct"] == 70.00

    claim = fx.submit_claim(sc)
    assert claim["per_cfm_candidate_cents"] == 270000
    assert claim["tier_bonus_pct"] == expected_tier_bonus_pct(75.00)
    assert claim["tier_bonus_pct"] == 0.10
    assert claim["tier_bonus_pct"] != 0.05
    assert claim["capped_subtotal_cents"] == 297000
    assert claim["admin_fee_cents"] == 14850
    assert claim["payable_cents"] == 282150

    program = sc.read_program()
    assert_program_ledger(program, 282150, 0, 4717850)


def test_a_programme_out_of_budget_refuses_the_claim_instead_of_truncating_it(api):
    """The full payable is compared against the balance; no partial award is made.

    PRD 3.8: "Only then is the money computed, and the resulting `payable_cents`
    must fit inside the program's `remaining_budget_cents`; if it exceeds what is
    left, the claim is refused with `ERR_PROGRAM_BUDGET_EXCEEDED`."

    Design: Corner/validations/program_budget_ceiling_blocks_the_claim_at_creation
    """
    sc = fx.scenario_issued_report(api, program={"annual_budget_cents": 100000})
    program_before = sc.read_program()
    assert_program_ledger(program_before, 0, 0, 100000)

    validate_error(
        api.create_rebate_claim(
            f.rebate_claim_payload(sc.report_id, sc.program_id), ADMIN_HEADERS
        ),
        ERR_PROGRAM_BUDGET_EXCEEDED,
        422,
    )

    program = sc.read_program()
    assert_program_ledger(program, 0, 0, 100000)
    assert_program_ledger_identity(program)

    rows, meta = validate_paginated(
        api.list_rebate_claims(ADMIN_HEADERS, utility_program_id=sc.program_id)
    )
    assert rows == []
    assert meta["total_count"] == 0

    # The report is untouched and stays claimable if the budget is later raised.
    assert sc.read_report()["status"] == REPORT_ISSUED


def test_the_whole_house_minimum_refuses_a_claim_whose_own_system_passed(api):
    """The guarantee reads the system basis; the programme minimum reads the whole house.

    PRD 3.8: "First, the report's `reduction_pct_whole_house_basis` must reach the
    program's `min_reduction_pct`; strictly below it, the claim is refused with
    `ERR_REBATE_REDUCTION_BELOW_PROGRAM_MINIMUM`."

    Design: Corner/validations/whole_house_shortfall_blocks_a_claim_whose_own_system_passed
    """
    sc = fx.scenario_post_verified(api)
    sibling = fx.add_duct_system(sc, system_label="AHU-2", lab_reference="LAB-1002")
    fx.add_accepted_leakage_test(sc, duct_system=sibling, measured_leakage_cfm=200.0)

    report = fx.draft_report(sc)
    assert report["reduction_pct_system_basis"] == 81.67
    assert report["guarantee_met"] is True
    assert report["reduction_pct_whole_house_basis"] == 49.00
    issued = fx.issue_report(sc)
    assert issued["status"] == REPORT_ISSUED

    validate_error(
        api.create_rebate_claim(
            f.rebate_claim_payload(
                sc.report_id, sc.program_id, documentation_bundle_ref="BUNDLE-2SYS"
            ),
            ADMIN_HEADERS,
        ),
        ERR_REBATE_REDUCTION_BELOW_PROGRAM_MINIMUM,
        422,
    )

    program = sc.read_program()
    assert_program_ledger(program, 0, 0, 5000000)
    _rows, meta = validate_paginated(
        api.list_rebate_claims(ADMIN_HEADERS, verification_report_id=sc.report_id)
    )
    assert meta["total_count"] == 0
    assert sc.read_report()["status"] == REPORT_ISSUED


def test_one_read_of_a_claim_exposes_the_whole_money_derivation(api):
    """Both candidates, the basis, the bonus, the cap, the fee and the payable.

    PRD 3.8 fixes every field of the derivation, and PRD 2.3: "`total_count` is the
    size of the filtered population, not the size of the returned page, so applying a
    filter shrinks `total_count`." PRD 2.8 rung 4: "every identifier in the path and
    every foreign key in the payload resolves to a live row, else the matching
    not-found error (404)."

    Design: Corner/endpoints/rebate_claim_read_and_filtered_list_expose_the_frozen_money_breakdown
    """
    sc = fx.scenario_submitted_claim(api)
    claim = validate_success(api.get_rebate_claim(sc.claim_id, INSPECTOR_HEADERS))

    assert claim["per_cfm_candidate_cents"] == 294000
    assert claim["percent_of_invoice_candidate_cents"] == 144000
    assert claim["basis_applied"] == REBATE_BASIS_PER_CFM
    assert claim["tier_bonus_pct"] == 0.10
    assert claim["capped_subtotal_cents"] == 323400
    assert claim["capped_subtotal_cents"] < 500000
    assert claim["admin_fee_cents"] == expected_admin_fee_cents(323400)
    assert claim["payable_cents"] == 307230
    assert claim["committed"] is True
    assert claim["inspector_outcome"] == INSPECTOR_PENDING
    assert claim["status"] == CLAIM_SUBMITTED

    by_program, program_meta = validate_paginated(
        api.list_rebate_claims(ADMIN_HEADERS, utility_program_id=sc.program_id)
    )
    assert program_meta["total_count"] == 1
    assert by_program[0]["id"] == sc.claim_id

    by_report, report_meta = validate_paginated(
        api.list_rebate_claims(
            ADMIN_HEADERS,
            verification_report_id=sc.report_id,
            status=CLAIM_SUBMITTED,
        )
    )
    assert report_meta["total_count"] == 1
    assert by_report[0]["id"] == sc.claim_id

    empty, empty_meta = validate_paginated(
        api.list_rebate_claims(ADMIN_HEADERS, status=CLAIM_PAID)
    )
    assert empty == []
    assert empty_meta["total_count"] == 0
    assert empty_meta["has_more"] is False

    validate_error(
        api.get_rebate_claim(NON_EXISTENT_UUID, ADMIN_HEADERS),
        ERR_REBATE_CLAIM_NOT_FOUND,
        404,
    )


def test_the_committing_write_already_carries_the_money_it_committed(api):
    """The claim create response, and every read taken after it, agree immediately.

    PRD 2.11: "Submitting a claim adds its `payable_cents` to
    `committed_rebate_cents` and therefore lowers `remaining_budget_cents` by the same
    amount", and the identity behind it: "`remaining_budget_cents` is
    `annual_budget_cents` less `committed_rebate_cents` less `paid_rebate_cents`."
    PRD 3.1 fixes the denormalised counters the same write touches:
    "`duct_system_count` counts every duct system under the project regardless of
    eligibility, while `eligible_duct_system_count` counts only those whose
    `eligibility_status` reads `ELIGIBLE`", and the technician's counter "tracks how
    many of the technician's sealing runs are still live".

    Design: Corner/consistency_model/denormalised_counters_and_the_money_ledger_are_correct_in_the_causing_response
    """
    sc = fx.scenario_issued_report(api)
    before = sc.read_program()
    assert_program_ledger(before, 0, 0, 5000000)

    causing = fx.submit_claim(sc, documentation_bundle_ref="BUNDLE-IMM")
    assert causing["payable_cents"] == 307230
    assert causing["basis_applied"] == REBATE_BASIS_PER_CFM
    assert causing["committed"] is True

    after = sc.read_program()
    assert_program_ledger(after, 307230, 0, 4692770)
    assert_program_ledger_identity(after)

    again = validate_success(api.get_utility_program(sc.program_id, INSPECTOR_HEADERS))
    assert again["committed_rebate_cents"] == 307230
    assert again["remaining_budget_cents"] == 4692770

    listed, meta = validate_paginated(
        api.list_rebate_claims(
            ADMIN_HEADERS, utility_program_id=sc.program_id, status=CLAIM_SUBMITTED
        )
    )
    assert meta["total_count"] == 1
    assert listed[0]["id"] == causing["id"]
    assert listed[0]["payable_cents"] == 307230

    project = sc.read_project()
    assert project["duct_system_count"] == 1
    assert project["eligible_duct_system_count"] == 1
    assert sc.read_technician()["open_seal_job_count"] == 0
