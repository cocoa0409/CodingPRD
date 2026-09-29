"""Collecting the Customer Facility Charge and filling the CFC trust."""

from test_helpers import (
    ADMIN,
    AUDITOR,
    TREASURY,
    ApiErrorId,
    assert_bond_coverage_posture,
    assert_remittance,
    assert_remittance_split_sums_to_receipt,
    assert_trust_conservation,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)


def _provisional_then_final(api):
    """One 2026-01 report billed provisionally at 4,000 self-reported days, then audited
    upward to 5,000 days so the FINAL basis diverges."""
    scenario = fx.setup_active_agreement(api)
    agreement_id, operator = scenario["agreement"]["id"], scenario["operator"]
    report = fx.create_report(
        api, agreement_id, operator,
        period_year=2026, period_month=1,
        reported_gross_revenue_cents=5_000_000,
        reported_on_airport_transaction_days=4_000,
    )
    fx.submit_report(api, report["id"], operator)
    provisional = fx.create_remittance(
        api, agreement_id, report["id"], operator, "PROVISIONAL"
    )
    fx.begin_audit(api, report["id"])
    fx.accept_report(
        api, report["id"],
        audited_gross_revenue_cents=5_000_000,
        audited_on_airport_transaction_days=5_000,
    )
    final = fx.create_remittance(api, agreement_id, report["id"], operator, "FINAL")
    return scenario, provisional, final


def test_provisional_basis_bills_self_reported_days(api):
    """PRD §3.6: "On the `PROVISIONAL` basis the billable transaction days are the report's
    `reported_on_airport_transaction_days` — the operator's own figure, billed before the
    audit confirms it, so that cash reaches the trust on schedule."
    PRD §3.6: "`expected_amount_cents` is the billable transaction days multiplied by the
    facility's `cfc_rate_per_transaction_day_cents`; the product is exact and no rounding
    occurs."
    PRD §3.6: "Its `due_date` is the last calendar day of the month named by the report's
    `period_year` and `period_month`, advanced by the facility's `remittance_grace_days`
    days."

    Design: Difficulty/dual_variant_calc/cfc_remittance_provisional_vs_final_transaction_day_basis
    """
    _scenario, provisional, _final = _provisional_then_final(api)

    stored = validate_success(api.get_remittance(provisional["id"], ADMIN))

    assert_remittance(stored)
    assert stored["expected_amount_cents"] == 2_000_000, (
        "4,000 self-reported days at 500 cents a day is 2,000,000 cents"
    )
    assert stored["due_date"] == "2026-02-20", (
        "2026-01-31 advanced by the 20-day grace period is 2026-02-20"
    )
    assert stored["remittance_basis"] == "PROVISIONAL"


def test_final_basis_bills_audited_days(api):
    """PRD §3.6: "On the `FINAL` basis the billable transaction days are the report's
    `audited_on_airport_transaction_days`."
    PRD §3.6: "The two bases therefore differ by exactly the difference between audited and
    reported days multiplied by that rate."
    PRD §3.6: "A new remittance opens with `status` `PENDING`, `amount_received_cents` of 0,
    `shortfall_cents` equal to `expected_amount_cents`, and `allocated_to_debt_service_cents`,
    `allocated_to_om_cents`, `allocated_to_capital_cents` and `allocated_to_unallocated_cents`
    all at 0."

    Design: Difficulty/dual_variant_calc/cfc_remittance_provisional_vs_final_transaction_day_basis
    """
    _scenario, provisional, final = _provisional_then_final(api)

    assert final["expected_amount_cents"] == 2_500_000, (
        "5,000 audited days at 500 cents a day is 2,500,000 cents"
    )
    assert (
        final["expected_amount_cents"] - provisional["expected_amount_cents"] == 500_000
    ), "the two bases diverge by 1,000 days times the 500 cent rate"
    assert final["status"] == "PENDING"
    assert final["shortfall_cents"] == 2_500_000
    assert final["due_date"] == "2026-02-20"


def test_deficient_branch_sweeps_the_whole_receipt_to_debt_service(api):
    """PRD §3.6: "While `bond_coverage_status` is `DEFICIENT`, the whole receipt is swept
    toward debt service: the amount sent is the smaller of the arriving cents and the
    debt-service gap."
    PRD §3.6: "Bucket two is the O&M reserve, fed from whatever the first bucket left over:
    twenty-five percent of that residual — the residual multiplied by 2,500 basis points,
    divided by 10,000 and truncated downward — capped at the O&M gap. Bucket three is the
    capital fund, fed from whatever the second bucket left over, capped at the capital gap,
    which is the greater of zero and `capital_fund_cap_cents` minus
    `trust_capital_fund_cents`. Bucket four is residue: everything the capital bucket could
    not take."
    PRD §2.8: "It is recomputed whenever any trust bucket moves: it reads `SATISFIED` when the
    sum of `trust_debt_service_reserve_cents` and `trust_debt_service_funded_cents` is greater
    than or equal to `ds_reserve_requirement_cents`, and `DEFICIENT` otherwise."

    Design: Difficulty/combinatorial_formula/cfc_waterfall_conditional_sweep_with_nested_min_max_caps
    """
    scenario = fx.setup_two_receipt_trust(api, receive_second=False)

    fx.receive_cash(api, scenario["remittance_2"]["id"], 4_000_000)

    facility = validate_success(api.get_facility(scenario["facility"]["id"], ADMIN))
    assert facility["trust_debt_service_reserve_cents"] == 5_000_000, (
        "the second receipt is clamped by the remaining 3,000,000 cent debt-service gap"
    )
    assert facility["trust_om_reserve_cents"] == 250_000, (
        "25% of the 1,000,000 cent residual is 250,000 cents"
    )
    assert facility["trust_capital_fund_cents"] == 750_000
    assert facility["trust_unallocated_cents"] == 0
    assert facility["trust_debt_service_funded_cents"] == 0
    assert facility["trust_lifetime_received_cents"] == 6_000_000
    assert facility["bond_coverage_status"] == "SATISFIED"
    assert facility["funded_obligation_count"] == 0
    assert_trust_conservation(facility)
    assert_bond_coverage_posture(facility)


def test_remittance_records_its_own_waterfall_split(api):
    """PRD §3.6: "Those four amounts are then added to `trust_debt_service_reserve_cents`,
    `trust_om_reserve_cents`, `trust_capital_fund_cents` and `trust_unallocated_cents`
    respectively, the whole receipt is added to `trust_lifetime_received_cents`, and the same
    four amounts accumulate on the remittance as `allocated_to_debt_service_cents`,
    `allocated_to_om_cents`, `allocated_to_capital_cents` and
    `allocated_to_unallocated_cents`."
    PRD §3.6: "Because every share is truncated downward and the residue bucket absorbs
    whatever the earlier three declined, the four amounts always sum to exactly the cents
    supplied in the receipt: no cent is ever lost, and none is ever invented."

    Design: Difficulty/combinatorial_formula/cfc_waterfall_conditional_sweep_with_nested_min_max_caps
    """
    scenario = fx.setup_two_receipt_trust(api, receive_second=False)

    received = fx.receive_cash(api, scenario["remittance_2"]["id"], 4_000_000)

    assert received["allocated_to_debt_service_cents"] == 3_000_000
    assert received["allocated_to_om_cents"] == 250_000
    assert received["allocated_to_capital_cents"] == 750_000
    assert received["allocated_to_unallocated_cents"] == 0
    assert received["status"] == "RECONCILED"
    assert received["shortfall_cents"] == 0
    assert_remittance_split_sums_to_receipt(received)


def test_zero_expectation_reconciles_on_a_zero_receipt(api):
    """PRD §3.6: "A remittance whose `expected_amount_cents` is zero reconciles on a receipt
    of zero and moves no cents through the trust at all."
    PRD §3.6: "**Hop one** accumulates `amount_received_cents` on the remittance and
    recomputes `shortfall_cents` as the greater of zero and `expected_amount_cents` minus the
    cumulative `amount_received_cents`, so a reconciled remittance carries a `shortfall_cents`
    of 0."
    PRD §3.6: "Its `due_date` is the last calendar day of the month named by the report's
    `period_year` and `period_month`, advanced by the facility's `remittance_grace_days`
    days."

    Design: Difficulty/boundary_precision_check/zero_transaction_day_remittance_reconciles_moving_no_cents
    """
    scenario = fx.setup_active_agreement(api)
    agreement_id, operator = scenario["agreement"]["id"], scenario["operator"]
    report = fx.create_report(
        api, agreement_id, operator,
        period_year=2026, period_month=6,
        reported_gross_revenue_cents=0,
        reported_on_airport_transaction_days=0,
    )
    fx.submit_report(api, report["id"], operator)
    remittance = fx.create_remittance(
        api, agreement_id, report["id"], operator, "PROVISIONAL"
    )
    assert remittance["expected_amount_cents"] == 0

    received = fx.receive_cash(api, remittance["id"], 0)

    assert received["status"] == "RECONCILED"
    assert received["amount_received_cents"] == 0
    assert received["shortfall_cents"] == 0
    assert received["due_date"] == "2026-07-20"


def test_zero_receipt_moves_no_cents_through_the_trust(api):
    """PRD §3.6: "A remittance whose `expected_amount_cents` is zero reconciles on a receipt
    of zero and moves no cents through the trust at all."
    PRD §2.8: "It is recomputed whenever any trust bucket moves: it reads `SATISFIED` when the
    sum of `trust_debt_service_reserve_cents` and `trust_debt_service_funded_cents` is greater
    than or equal to `ds_reserve_requirement_cents`, and `DEFICIENT` otherwise."

    Design: Difficulty/boundary_precision_check/zero_transaction_day_remittance_reconciles_moving_no_cents
    """
    scenario = fx.setup_active_agreement(api)
    agreement_id, operator = scenario["agreement"]["id"], scenario["operator"]
    report = fx.create_report(
        api, agreement_id, operator,
        period_year=2026, period_month=6,
        reported_gross_revenue_cents=0,
        reported_on_airport_transaction_days=0,
    )
    fx.submit_report(api, report["id"], operator)
    remittance = fx.create_remittance(
        api, agreement_id, report["id"], operator, "PROVISIONAL"
    )

    received = fx.receive_cash(api, remittance["id"], 0)

    assert received["allocated_to_debt_service_cents"] == 0
    assert received["allocated_to_om_cents"] == 0
    assert received["allocated_to_capital_cents"] == 0
    assert received["allocated_to_unallocated_cents"] == 0
    facility = validate_success(api.get_facility(scenario["facility"]["id"], ADMIN))
    assert facility["trust_lifetime_received_cents"] == 0
    assert facility["trust_debt_service_reserve_cents"] == 0
    assert facility["bond_coverage_status"] == "DEFICIENT"


def test_partial_receipt_leaves_a_shortfall(api):
    """PRD §3.6: "A receipt is accepted from `PENDING`, `DELINQUENT` or `RECEIVED`, and where
    it lands depends on the resulting cumulative position: when the already-received cents
    plus this call's cents remain strictly below `expected_amount_cents`, the remittance
    becomes `RECEIVED`; when they reach or exceed `expected_amount_cents`, it becomes the
    terminal `RECONCILED`."
    PRD §3.6: "**Hop one** accumulates `amount_received_cents` on the remittance and
    recomputes `shortfall_cents` as the greater of zero and `expected_amount_cents` minus the
    cumulative `amount_received_cents`, so a reconciled remittance carries a `shortfall_cents`
    of 0."
    PRD §3.6: "The waterfall itself is strictly ordered, and only the cents supplied in this
    one call flow through it — previously received cents are never re-run, and every bucket is
    read at its value as of the start of the request."

    Design: Corner/state_machines/partial_cfc_receipt_leaves_remittance_received_with_shortfall
    """
    scenario = fx.setup_active_agreement(api)
    agreement_id, operator = scenario["agreement"]["id"], scenario["operator"]
    report = fx.create_accepted_report(
        api, agreement_id, operator,
        period_year=2026, period_month=1,
        reported_gross_revenue_cents=5_000_000,
        reported_on_airport_transaction_days=4_000,
    )
    remittance = fx.create_remittance(api, agreement_id, report["id"], operator, "FINAL")

    first = fx.receive_cash(api, remittance["id"], 1_200_000)
    assert first["status"] == "RECEIVED"
    assert first["shortfall_cents"] == 800_000
    facility = validate_success(api.get_facility(scenario["facility"]["id"], ADMIN))
    assert facility["trust_debt_service_reserve_cents"] == 1_200_000

    second = fx.receive_cash(api, remittance["id"], 800_000)

    assert second["status"] == "RECONCILED"
    assert second["shortfall_cents"] == 0
    assert second["amount_received_cents"] == 2_000_000
    assert second["allocated_to_debt_service_cents"] == 2_000_000
    assert second["allocated_to_capital_cents"] == 0
    facility = validate_success(api.get_facility(scenario["facility"]["id"], ADMIN))
    assert facility["trust_debt_service_reserve_cents"] == 2_000_000
    assert facility["trust_lifetime_received_cents"] == 2_000_000
    assert_trust_conservation(facility)


def test_capital_cap_spills_residue_into_unallocated(api):
    """PRD §3.6: "While it is `SATISFIED`, only a share is swept: sixty percent of the
    arriving cents — that is, the arriving cents multiplied by 6,000 basis points, divided by
    10,000 and truncated downward to a whole cent — capped at the debt-service gap."
    PRD §3.6: "Bucket three is the capital fund, fed from whatever the second bucket left
    over, capped at the capital gap, which is the greater of zero and `capital_fund_cap_cents`
    minus `trust_capital_fund_cents`. Bucket four is residue: everything the capital bucket
    could not take."
    PRD §2.8: "Note the consequence at registration time: a facility whose
    `ds_reserve_requirement_cents` is greater than zero begins life `DEFICIENT`, while a
    facility that requires no debt-service reserve at all begins `SATISFIED`."

    Design: Corner/calculations/waterfall_capital_cap_spills_the_residue_into_unallocated
    """
    scenario = fx.setup_active_agreement(
        api,
        facility_overrides={
            "code": "SLC",
            "name": "SLC ConRAC",
            "ds_reserve_requirement_cents": 0,
            "om_reserve_requirement_cents": 0,
            "capital_fund_cap_cents": 100_000,
            "overflow_lot_stalls": 50,
        },
    )
    agreement_id, operator = scenario["agreement"]["id"], scenario["operator"]
    report = fx.create_accepted_report(
        api, agreement_id, operator,
        period_year=2026, period_month=1,
        reported_gross_revenue_cents=5_000_000,
        reported_on_airport_transaction_days=4_000,
    )
    remittance = fx.create_remittance(api, agreement_id, report["id"], operator, "FINAL")

    received = fx.receive_cash(api, remittance["id"], 2_000_000)

    facility = validate_success(api.get_facility(scenario["facility"]["id"], ADMIN))
    assert facility["trust_debt_service_reserve_cents"] == 0, (
        "a zero debt-service gap clamps the 60% sweep to nothing"
    )
    assert facility["trust_om_reserve_cents"] == 0
    assert facility["trust_capital_fund_cents"] == 100_000
    assert facility["trust_unallocated_cents"] == 1_900_000
    assert facility["trust_lifetime_received_cents"] == 2_000_000
    assert facility["bond_coverage_status"] == "SATISFIED"
    assert received["allocated_to_capital_cents"] == 100_000
    assert received["allocated_to_unallocated_cents"] == 1_900_000
    assert_remittance_split_sums_to_receipt(received)


def test_second_provisional_remittance_is_rejected(api):
    """PRD §3.6: "First, duplication: at most one remittance may exist for a given `report_id`
    and `remittance_basis` pair in any status other than `RECONCILED`, and a second one is
    rejected with `ERR_DUPLICATE_REMITTANCE` (HTTP 409)."

    Design: Corner/validations/second_provisional_remittance_for_the_same_report_is_rejected
    """
    scenario = fx.setup_active_agreement(api)
    agreement_id, operator = scenario["agreement"]["id"], scenario["operator"]
    report = fx.create_report(api, agreement_id, operator, period_year=2026, period_month=1)
    fx.submit_report(api, report["id"], operator)
    fx.create_remittance(api, agreement_id, report["id"], operator, "PROVISIONAL")

    response = api.create_remittance(
        f.remittance_payload(agreement_id, report["id"], remittance_basis="PROVISIONAL"),
        operator,
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_REMITTANCE.value, 409)
    _rows, meta = validate_paginated(
        api.list_remittances(ADMIN, params={"report_id": report["id"]})
    )
    assert meta["total_count"] == 1


def test_final_remittance_against_a_draft_report_is_rejected(api):
    """PRD §3.6: "Third, basis admissibility: `PROVISIONAL` is only admissible while the
    report sits in `SUBMITTED` or `UNDER_AUDIT`, and `FINAL` is only admissible once the
    report has reached `ACCEPTED`; any other pairing is rejected with
    `ERR_REMITTANCE_BASIS_MISMATCH` (HTTP 422)."

    Design: Corner/validations/final_remittance_against_a_draft_report_is_rejected
    """
    scenario = fx.setup_active_agreement(api)
    agreement_id, operator = scenario["agreement"]["id"], scenario["operator"]
    report = fx.create_report(api, agreement_id, operator, period_year=2026, period_month=1)

    response = api.create_remittance(
        f.remittance_payload(agreement_id, report["id"], remittance_basis="FINAL"), operator
    )

    validate_error(response, ApiErrorId.ERR_REMITTANCE_BASIS_MISMATCH.value, 422)
    _rows, meta = validate_paginated(
        api.list_remittances(ADMIN, params={"agreement_id": agreement_id})
    )
    assert meta["total_count"] == 0


def test_remittance_naming_another_agreements_report_is_rejected(api):
    """PRD §3.6: "Second, referential agreement: the report named by `report_id` must itself
    belong to the agreement named by `agreement_id` in the same body, and a cross-wired pair
    is rejected with `ERR_REPORT_AGREEMENT_MISMATCH` (HTTP 422)."

    Design: Corner/validations/remittance_pointing_at_another_agreements_report_is_rejected
    """
    scenario = fx.setup_active_agreement(api)
    other = fx.add_brand_with_active_agreement(
        api, scenario["facility"]["id"], "BUD", "Budline Auto Rental"
    )
    other_report = fx.create_report(
        api, other["agreement"]["id"], other["operator"],
        period_year=2026, period_month=1,
    )
    fx.submit_report(api, other_report["id"], other["operator"])

    response = api.create_remittance(
        f.remittance_payload(
            scenario["agreement"]["id"], other_report["id"], remittance_basis="PROVISIONAL"
        ),
        scenario["operator"],
    )

    validate_error(response, ApiErrorId.ERR_REPORT_AGREEMENT_MISMATCH.value, 422)
    _rows, meta = validate_paginated(
        api.list_remittances(ADMIN, params={"report_id": other_report["id"]})
    )
    assert meta["total_count"] == 0


def test_clock_marks_an_overdue_remittance_delinquent(api):
    """PRD §3.6: "When the logical clock is moved past a `PENDING` remittance's `due_date`,
    the remittance moves `PENDING → DELINQUENT` and its agreement's `compliance_status` moves
    `COMPLIANT → DELINQUENT`; both rows advance their `version` by 1, and the sweep is counted
    in the clock response's `delinquent_remittance_count`."
    PRD §3.6: "Finally, if the receipt reconciled the last outstanding delinquency and no
    remittance of that agreement remains in `DELINQUENT`, the agreement's `compliance_status`
    returns `DELINQUENT → COMPLIANT`."

    Design: Corner/state_machines/clock_advance_marks_overdue_remittance_delinquent_and_agreement_noncompliant
    """
    scenario = fx.setup_active_agreement(api)
    agreement_id, operator = scenario["agreement"]["id"], scenario["operator"]
    report = fx.create_accepted_report(
        api, agreement_id, operator,
        period_year=2026, period_month=8,
        reported_gross_revenue_cents=5_000_000,
        reported_on_airport_transaction_days=4_000,
    )
    remittance = fx.create_remittance(api, agreement_id, report["id"], operator, "FINAL")
    assert remittance["due_date"] == "2026-09-20"

    summary = validate_success(
        api.set_clock(f.clock_payload("2026-09-21T00:00:00Z"), ADMIN)
    )
    assert summary["delinquent_remittance_count"] == 1
    swept = validate_success(api.get_remittance(remittance["id"], ADMIN))
    assert swept["status"] == "DELINQUENT"
    agreement = validate_success(api.get_agreement(agreement_id, ADMIN))
    assert agreement["compliance_status"] == "DELINQUENT"

    fx.receive_cash(api, remittance["id"], 2_000_000)

    settled = validate_success(api.get_remittance(remittance["id"], ADMIN))
    assert settled["status"] == "RECONCILED"
    agreement = validate_success(api.get_agreement(agreement_id, ADMIN))
    assert agreement["compliance_status"] == "COMPLIANT"
    assert agreement["contract_status"] == "ACTIVE"
    facility = validate_success(api.get_facility(scenario["facility"]["id"], ADMIN))
    assert facility["current_utc"] == "2026-09-21T00:00:00Z"


def test_audit_officer_cannot_receive_cfc_cash(api):
    """PRD §2.1: "A caller whose role is recognised but who is not among the roles authorised
    for the endpoint being called receives `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §4: "Record CFC cash into the trust, driving the five-hop waterfall / covenant /
    auto-funding / project-release cascade | FinanceOfficer"

    Design: Corner/rbac/audit_officer_cannot_receive_a_cfc_remittance
    """
    scenario = fx.setup_active_agreement(api)
    agreement_id, operator = scenario["agreement"]["id"], scenario["operator"]
    report = fx.create_report(api, agreement_id, operator, period_year=2026, period_month=1)
    fx.submit_report(api, report["id"], operator)
    remittance = fx.create_remittance(
        api, agreement_id, report["id"], operator, "PROVISIONAL"
    )

    response = api.receive_remittance(
        remittance["id"], f.receive_payload(2_000_000), AUDITOR
    )

    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)
    stored = validate_success(api.get_remittance(remittance["id"], ADMIN))
    assert stored["status"] == "PENDING"
    assert stored["amount_received_cents"] == 0
    facility = validate_success(api.get_facility(scenario["facility"]["id"], ADMIN))
    assert facility["trust_lifetime_received_cents"] == 0


def test_receive_response_already_carries_the_cascaded_fields(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will
    return the created or updated resource object in the data field."
    PRD §3.6: "While `bond_coverage_status` is `DEFICIENT`, the whole receipt is swept toward
    debt service: the amount sent is the smaller of the arriving cents and the debt-service
    gap."
    PRD §3.6: "Those four amounts are then added to `trust_debt_service_reserve_cents`,
    `trust_om_reserve_cents`, `trust_capital_fund_cents` and `trust_unallocated_cents`
    respectively, the whole receipt is added to `trust_lifetime_received_cents`, and the same
    four amounts accumulate on the remittance as `allocated_to_debt_service_cents`,
    `allocated_to_om_cents`, `allocated_to_capital_cents` and
    `allocated_to_unallocated_cents`."

    Design: Corner/consistency_model/remittance_receipt_response_already_reflects_every_cascaded_field
    """
    scenario = fx.setup_active_agreement(api)
    agreement_id, operator = scenario["agreement"]["id"], scenario["operator"]
    report = fx.create_accepted_report(
        api, agreement_id, operator,
        period_year=2026, period_month=1,
        reported_gross_revenue_cents=5_000_000,
        reported_on_airport_transaction_days=4_000,
    )
    remittance = fx.create_remittance(api, agreement_id, report["id"], operator, "FINAL")

    received = validate_success(
        api.receive_remittance(remittance["id"], f.receive_payload(2_000_000), TREASURY)
    )

    assert received["status"] == "RECONCILED", (
        "the receive response body itself must already show the terminal status"
    )
    assert received["allocated_to_debt_service_cents"] == 2_000_000, (
        "the receive response body itself must already show the waterfall split"
    )
    facility = validate_success(api.get_facility(scenario["facility"]["id"], TREASURY))
    assert facility["trust_debt_service_reserve_cents"] == 2_000_000
    assert facility["trust_lifetime_received_cents"] == 2_000_000
    assert facility["bond_coverage_status"] == "DEFICIENT"
